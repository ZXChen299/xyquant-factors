import base64
import concurrent.futures
import hashlib
import io
import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import threading
import time
import unittest
from unittest.mock import patch
import urllib.error
import urllib.parse
import urllib.request

from auth_client import AuthClient, ClientError, ORIGIN
from login_tasks import LoginTasks


class FakeAuth:
    def __init__(self):
        self.connected = False
        self.calls = 0

    def identity(self):
        if not self.connected:
            raise ClientError('No login', 'login_required')
        return dict(customer_id='fixture', username='test', connection_id='connection',
                    connection_expires_at=time.time() + 3600)

    def login(self, **kwargs):
        self.calls += 1
        self.options = kwargs
        kwargs['on_ready'](ORIGIN + '/factors/oauth/authorize?state=public-fixture')
        self.connected = True
        return {**self.identity(), 'access_token': 'must-never-leave-auth'}

    def disconnect(self):
        self.connected = False


class LoginTaskTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.root = Path(self.temp.name)
        self.auth = FakeAuth()
        self.tasks = LoginTasks(self.root, self.auth)

    def tearDown(self):
        self.temp.cleanup()

    def test_start_fast_deduplicates_and_status_is_local(self):
        with concurrent.futures.ThreadPoolExecutor(max_workers=5) as pool:
            results = list(pool.map(lambda _: self.tasks.start(spawn=False), range(5)))
        self.assertEqual(len({row['login_id'] for row in results}), 1)
        self.assertEqual(results[0]['status'], 'preparing')
        self.assertFalse(self.tasks.status()['verified_by_server'])
        self.tasks.run(results[0]['login_id'])
        row = self.tasks.get(results[0]['login_id'])
        self.assertEqual(row['status'], 'connected')
        self.assertNotIn('must-never-leave-auth', json.dumps(row))
        self.assertIsNone(self.auth.options['open_browser'])
        self.assertTrue(self.tasks.start()['connected'])
        self.assertEqual(self.auth.calls, 1)

    def test_separate_processes_share_one_pending_task(self):
        script = ('import json,sys; from login_tasks import LoginTasks; '
                  'from test_login_tasks import FakeAuth; '
                  'print(json.dumps(LoginTasks(sys.argv[1],FakeAuth()).start(spawn=False)))')
        workers = [subprocess.Popen([sys.executable, '-B', '-c', script, str(self.root)],
                   cwd=Path(__file__).parent, stdout=subprocess.PIPE, stderr=subprocess.PIPE,
                   creationflags=getattr(subprocess, 'CREATE_NO_WINDOW', 0)) for _ in range(4)]
        results = []
        for worker in workers:
            output, error = worker.communicate(timeout=20)
            self.assertEqual(worker.returncode, 0, error.decode(errors='replace'))
            results.append(json.loads(output))
        self.assertEqual(len({row['login_id'] for row in results}), 1)

    def test_waiting_link_exists_only_during_pending_login(self):
        task = self.tasks.start(spawn=False)
        captured = []
        def login(**kwargs):
            kwargs['on_ready'](ORIGIN + '/factors/oauth/authorize?state=public')
            captured.append(self.tasks.get(task['login_id']))
            raise ClientError('已取消登录。', 'login_cancelled')
        self.auth.login = login
        self.tasks.run(task['login_id'])
        self.assertEqual(captured[0]['status'], 'waiting_authorization')
        self.assertIn('authorization_url', captured[0])
        done = self.tasks.get(task['login_id'])
        self.assertEqual(done['status'], 'cancelled')
        self.assertNotIn('authorization_url', done)

    def test_timeout_and_dead_worker_are_explicit(self):
        first = self.tasks.start(spawn=False)
        with self.tasks.db() as db:
            db.execute('UPDATE login_tasks SET expires=? WHERE id=?', (time.time() - 1, first['login_id']))
        self.assertEqual(self.tasks.get(first['login_id'])['status'], 'expired')
        second = self.tasks.start(spawn=False)
        with self.tasks.db() as db:
            db.execute('UPDATE login_tasks SET worker_pid=? WHERE id=?', (12345678, second['login_id']))
        with patch('login_tasks.process_alive', return_value=False):
            self.assertEqual(self.tasks.get(second['login_id'])['status'], 'interrupted')
        third = self.tasks.start(spawn=False)
        with self.tasks.db() as db:
            db.execute('UPDATE login_tasks SET updated=? WHERE id=?', (time.time() - 31, third['login_id']))
        self.assertEqual(self.tasks.get(third['login_id'])['status'], 'interrupted')

    def test_disconnect_cancels_worker_before_clearing_credentials(self):
        task = self.tasks.start(spawn=False)
        def disconnect():
            self.assertTrue(self.tasks._cancelled(task['login_id']))
        self.auth.disconnect = disconnect
        self.assertEqual(self.tasks.disconnect()['status'], 'disconnected')
        self.tasks.run(task['login_id'])
        self.assertEqual(self.auth.calls, 0)
        self.assertEqual(self.tasks.get(task['login_id'])['status'], 'cancelled')

    def test_spawn_failure_is_reported_without_stuck_pending(self):
        with patch('login_tasks.spawn_worker', side_effect=ClientError('Cannot start', 'worker_start_failed')):
            task = self.tasks.start()
        self.assertEqual(task['status'], 'failed')
        self.assertEqual(task['error_code'], 'worker_start_failed')

    def test_invalid_id_and_unhandled_failure_are_safe(self):
        with self.assertRaises(ClientError):
            self.tasks.get('../credentials.dpapi')
        task = self.tasks.start(spawn=False)
        with patch.object(self.auth, 'login', side_effect=RuntimeError('secret exception detail')):
            self.tasks.run(task['login_id'])
        done = self.tasks.get(task['login_id'])
        self.assertEqual(done['status'], 'failed')
        self.assertNotIn('secret exception detail', json.dumps(done))


class AuthPluginTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.client = AuthClient(self.temp.name)

    def tearDown(self):
        self.temp.cleanup()

    def _run_callback(self, cancel_during_exchange=False):
        captured = {}
        cancelled = threading.Event()
        callback_threads = []
        def request(path, data=None, **kwargs):
            if path.endswith('/register'):
                captured['redirect'] = data['redirect_uris'][0]
                return {'client_id': 'test-client'}
            if path.endswith('/token'):
                verifier = data['code_verifier']
                self.assertEqual(captured['challenge'], base64.urlsafe_b64encode(hashlib.sha256(verifier.encode()).digest()).decode().rstrip('='))
                if cancel_during_exchange:
                    cancelled.set()
                return dict(customer_id='fixture', username='test', connection_id='test-connection',
                            connection_expires_at=time.time() + 3600, expires_in=600,
                            access_token='test-access-secret', refresh_token='test-refresh-secret')
            if path.endswith('/revoke'):
                captured['revoked'] = True
                return {}
            raise AssertionError(path)
        def on_ready(url):
            params = urllib.parse.parse_qs(urllib.parse.urlsplit(url).query)
            captured['challenge'] = params['code_challenge'][0]
            def callback():
                opener = urllib.request.build_opener(urllib.request.ProxyHandler({}))
                bad = captured['redirect'] + '?' + urllib.parse.urlencode(dict(state='wrong-state', iss=ORIGIN, code='not-accepted'))
                try:
                    opener.open(bad, timeout=5)
                except urllib.error.HTTPError as error:
                    captured['bad_status'] = error.code
                good = captured['redirect'] + '?' + urllib.parse.urlencode(dict(state=params['state'][0], iss=ORIGIN, code='fixture-code'))
                with opener.open(good, timeout=5) as response:
                    captured['html'] = response.read().decode()
            thread = threading.Thread(target=callback)
            callback_threads.append(thread)
            thread.start()
        try:
            with patch.object(self.client, 'json_request', request):
                result = self.client.login(open_browser=None, on_ready=on_ready, cancelled=cancelled.is_set, timeout=10)
                captured['result'] = result
        finally:
            for thread in callback_threads:
                thread.join(timeout=6)
        return captured

    def test_callback_validates_state_and_pkce_without_browser(self):
        captured = self._run_callback()
        self.assertEqual(captured['bad_status'], 400)
        self.assertIn('返回 Codex', captured['html'])
        self.assertEqual(captured['result']['customer_id'], 'fixture')
        self.assertNotIn('access_token', captured['result'])
        self.assertNotIn(b'test-refresh-secret', self.client.file.read_bytes())

    def test_cancel_during_exchange_does_not_save_credentials(self):
        with self.assertRaises(ClientError) as error:
            self._run_callback(cancel_during_exchange=True)
        self.assertEqual(error.exception.code, 'login_cancelled')
        self.assertFalse(self.client.file.exists())

    def test_expired_login_does_not_start_network_request(self):
        with patch.object(self.client, 'json_request') as request, self.assertRaises(ClientError) as error:
            self.client.login(open_browser=None, timeout=0)
        request.assert_not_called()
        self.assertEqual(error.exception.code, 'login_timeout')

    def test_invalidate_does_not_erase_concurrent_refresh(self):
        self.client._save(dict(issuer=ORIGIN, access_token='new-test-token'))
        self.client.invalidate('old-test-token')
        self.assertTrue(self.client.file.exists())
        self.client.invalidate('new-test-token')
        self.assertFalse(self.client.file.exists())

    def test_refresh_is_shared_across_real_processes(self):
        self.client._save(dict(issuer=ORIGIN, access_token='old-fixture', refresh_token='refresh-fixture',
                               client_id='client-fixture', connection_expires_at=time.time()+3600,
                               access_expires_at=0))
        script = '''import sys,time
from pathlib import Path
from auth_client import AuthClient
class FixtureClient(AuthClient):
    def json_request(self,*args,**kwargs):
        counter=self.root/'refresh-count.txt'
        count=int(counter.read_text()) if counter.exists() else 0
        counter.write_text(str(count+1))
        time.sleep(.05)
        return dict(access_token='fresh-fixture',refresh_token='rotated-fixture',expires_in=600)
client=FixtureClient(sys.argv[1])
assert client.access()=='fresh-fixture'
'''
        workers = [subprocess.Popen([sys.executable, '-B', '-c', script, str(self.client.root)],
                   cwd=Path(__file__).parent, stdout=subprocess.PIPE, stderr=subprocess.PIPE,
                   creationflags=getattr(subprocess, 'CREATE_NO_WINDOW', 0)) for _ in range(4)]
        for worker in workers:
            output, error = worker.communicate(timeout=20)
            self.assertEqual(worker.returncode, 0, error.decode(errors='replace'))
            self.assertEqual(output, b'')
        self.assertEqual((self.client.root/'refresh-count.txt').read_text(), '1')

    def test_http_error_classification(self):
        cases = [(403, {}, 'permission_denied'), (400, {}, 'invalid_request'),
                 (400, {'error': 'invalid_grant'}, 'login_required'),
                 (401, {}, 'login_required'), (429, {}, 'busy'), (503, {}, 'busy')]
        for code, body, expected in cases:
            error = urllib.error.HTTPError(ORIGIN, code, 'fixture', {}, io.BytesIO(json.dumps(body).encode()))
            with patch.object(self.client.opener, 'open', side_effect=error), self.assertRaises(ClientError) as raised:
                self.client.json_request('/factors/oauth/token', {'grant_type': 'refresh_token'})
            self.assertEqual(raised.exception.code, expected)


if __name__ == '__main__':
    unittest.main()
