import asyncio
import contextlib
import io
import json
from pathlib import Path
import tempfile
import threading
import time
import unittest
from unittest.mock import patch

import auth_async
from auth_client import AuthClient,ClientError,ORIGIN,mutex
import remote


class BlockingAuth:
    def __init__(self,root=None,delay=0.25,error=None):
        if root is not None:self.root=root
        self.delay=delay;self.error=error;self.calls=0;self.completed=threading.Event()
    def access(self):
        self.calls+=1
        try:
            time.sleep(self.delay)
            if self.error:raise self.error
            return 'synthetic-secret-token'
        finally:self.completed.set()


class AuthAsyncTests(unittest.TestCase):
    def test_asyncio_run_wall_clock_does_not_join_timed_out_auth(self):
        auth=BlockingAuth(delay=0.5)
        started=time.monotonic()
        with patch.object(remote,'CALL_BUDGET',0.025),self.assertRaises(ClientError) as cm:
            asyncio.run(remote.remote_call('list_factors',{},auth))
        elapsed=time.monotonic()-started
        self.assertEqual(cm.exception.code,'network_error')
        self.assertLess(elapsed,0.25)
        self.assertFalse(auth.completed.is_set())
        auth_async.drain(auth)
        self.assertEqual(auth.calls,1)

    def test_same_root_concurrent_calls_share_operation(self):
        with tempfile.TemporaryDirectory() as td:
            first,second=BlockingAuth(Path(td)),BlockingAuth(Path(td))
            async def both():return await asyncio.gather(auth_async.access(first,2),auth_async.access(second,2))
            self.assertEqual(asyncio.run(both()),['synthetic-secret-token']*2)
            self.assertEqual(first.calls+second.calls,1)
            auth_async.drain(first)

    def test_later_event_loop_shares_still_running_operation(self):
        auth=BlockingAuth(delay=0.25)
        with self.assertRaises(TimeoutError):asyncio.run(auth_async.access(auth,0.02))
        self.assertEqual(asyncio.run(auth_async.access(auth,2)),'synthetic-secret-token')
        self.assertEqual(auth.calls,1)
        auth_async.drain(auth)

    def test_different_roots_and_anonymous_instances_are_isolated(self):
        with tempfile.TemporaryDirectory() as td:
            objects=[BlockingAuth(Path(td)/'a',0.02),BlockingAuth(Path(td)/'b',0.02),BlockingAuth(delay=0.02),BlockingAuth(delay=0.02)]
            async def all_calls():return await asyncio.gather(*(auth_async.access(x,2) for x in objects))
            asyncio.run(all_calls())
            self.assertEqual([x.calls for x in objects],[1,1,1,1])

    def test_timed_out_exception_is_never_logged_and_future_cleans_up(self):
        auth=BlockingAuth(delay=0.06,error=RuntimeError('token=synthetic-secret'))
        errors=[]
        async def wait_then_fail():
            asyncio.get_running_loop().set_exception_handler(lambda loop,context:errors.append(context))
            with self.assertRaises(TimeoutError):await auth_async.access(auth,0.01)
            await asyncio.sleep(0.12)
        output=io.StringIO()
        with contextlib.redirect_stderr(output),contextlib.redirect_stdout(output):asyncio.run(wait_then_fail())
        self.assertEqual(output.getvalue(),'');self.assertEqual(errors,[])
        with auth_async._guard:self.assertNotIn(auth_async._key(auth),auth_async._inflight)

    def test_drain_never_starts_an_auth_operation(self):
        auth=BlockingAuth()
        auth_async.drain(auth)
        self.assertEqual(auth.calls,0)

    def test_worker_persists_failure_before_draining_existing_auth(self):
        import test_assistant
        fixture=test_assistant.AssistantTests();fixture.setUp()
        try:
            manager,task,job,project=fixture.prepare()
            auth=BlockingAuth(manager.root,delay=0.2);manager.auth=auth
            auth_async._start_or_share(auth)
            checked=[]
            def drain(who):
                with manager.db() as db:
                    row=db.execute('SELECT status,error_code FROM downloads WHERE id=?',(task['id'],)).fetchone()
                self.assertEqual(row['status'],'failed');self.assertEqual(row['error_code'],'network_error')
                auth_async.drain(who);checked.append(True)
                self.assertTrue(auth.completed.is_set())
                self.assertEqual(auth.calls,1)
                with auth_async._guard:self.assertNotIn(auth_async._key(auth),auth_async._inflight)
            with patch.object(manager,'perform',side_effect=ClientError('safe failure','network_error')),patch('downloads.drain_auth',side_effect=drain):
                manager.run()
            self.assertEqual(checked,[True])
        finally:
            fixture.tearDown()

    def test_invalid_token_cleanup_does_not_wait_for_credentials_lock(self):
        with tempfile.TemporaryDirectory() as td:
            auth=AuthClient(Path(td));auth._save(dict(issuer=ORIGIN,access_token='synthetic-old'))
            held,release=threading.Event(),threading.Event()
            def holder():
                with mutex('credentials',root=auth.root):
                    held.set();release.wait(2)
            thread=threading.Thread(target=holder,daemon=True);thread.start()
            try:
                self.assertTrue(held.wait(2))
                started=time.monotonic();auth.invalidate('synthetic-old')
                self.assertLess(time.monotonic()-started,0.2)
                self.assertTrue(auth.file.exists())
            finally:release.set();thread.join(timeout=2)

    def test_invalid_old_token_never_deletes_newer_credentials(self):
        with tempfile.TemporaryDirectory() as td:
            auth=AuthClient(Path(td));auth._save(dict(issuer=ORIGIN,access_token='synthetic-new'))
            auth.invalidate('synthetic-old')
            self.assertEqual(auth._read()['access_token'],'synthetic-new')
            auth.invalidate('synthetic-new')
            self.assertFalse(auth.file.exists())

    def test_invalid_cleanup_does_not_swallow_unrelated_client_errors(self):
        with tempfile.TemporaryDirectory() as td:
            auth=AuthClient(Path(td))
            with patch('auth_client.mutex',side_effect=ClientError('safe failure','permission_denied')):
                with self.assertRaises(ClientError) as error:auth.invalidate('synthetic-old')
            self.assertEqual(error.exception.code,'permission_denied')


if __name__=='__main__':unittest.main()
