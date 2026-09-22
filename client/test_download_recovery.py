import os
import errno
from pathlib import Path
import tempfile
import time
import unittest
from unittest.mock import patch

from auth_client import ClientError
from downloads import Downloads,safe_folder
import test_assistant


class DownloadRecoveryTests(unittest.TestCase):
    def setUp(self):
        self.fixture=test_assistant.AssistantTests()
        self.fixture.setUp()
        self.manager,self.task,self.job,self.project=self.fixture.prepare()

    def tearDown(self):
        self.fixture.tearDown()

    def complete(self):
        async def remote(*args,**kwargs):return self.job
        with patch('downloads.remote_call',remote):self.manager.perform(self.task)
        return self.manager.get(self.task['id'])

    def test_poll_detects_worker_crash_without_another_download(self):
        self.manager.update(self.task['id'],status='downloading')
        with self.manager.db() as db:
            db.execute('INSERT INTO download_worker VALUES(1,?,?)',(12345678,time.time()))
        restored=Downloads(self.manager.root,self.manager.auth)
        result=restored.get(self.task['id'])
        self.assertEqual(result['status'],'interrupted')
        self.assertEqual(result['error_code'],'interrupted')

    def test_queued_bootstrap_has_grace_then_reports_failure(self):
        self.assertEqual(self.manager.get(self.task['id'])['status'],'queued')
        with self.manager.db() as db:
            db.execute('UPDATE downloads SET updated=?',(time.time()-31,))
        result=self.manager.get(self.task['id'])
        self.assertEqual(result['status'],'interrupted')
        self.assertEqual(result['error_code'],'worker_start_failed')

    def test_active_worker_heartbeat_prevents_false_recovery(self):
        self.manager.update(self.task['id'],status='downloading')
        with self.manager.db() as db:
            db.execute('INSERT INTO download_worker VALUES(1,?,?)',(os.getpid(),time.time()))
        self.assertEqual(self.manager.get(self.task['id'])['status'],'downloading')

    def test_spawn_failure_is_durable_and_retryable(self):
        with patch.object(self.manager,'spawn_worker',side_effect=ClientError('Cannot run','worker_start_failed')):
            result=self.manager.start(self.task['job_id'],self.task['project'])
        self.assertEqual(result['status'],'failed')
        self.assertEqual(result['error_code'],'worker_start_failed')
        self.assertEqual(self.manager.start(self.task['job_id'],self.task['project'],spawn=False)['status'],'queued')

    def test_missing_ready_file_is_requeued_on_new_request(self):
        result=self.complete()
        Path(result['path']).unlink()
        self.assertEqual(self.manager.get(self.task['id'])['error_code'],'file_missing')
        retry=self.manager.start(self.task['job_id'],self.task['project'],spawn=False)
        self.assertEqual(retry['id'],self.task['id'])
        self.assertEqual(retry['status'],'queued')

    def test_same_size_changed_file_is_rejected_on_reuse(self):
        result=self.complete()
        path=Path(result['path'])
        path.write_bytes(b'x'*path.stat().st_size)
        with patch('downloads.file_hash',side_effect=AssertionError('Polling must not hash')):
            self.assertEqual(self.manager.get(self.task['id'])['status'],'ready')
        retry=self.manager.start(self.task['job_id'],self.task['project'],spawn=False)
        self.assertEqual(retry['status'],'failed')
        self.assertEqual(retry['error_code'],'file_conflict')
        self.assertEqual(path.read_bytes(),b'x'*len(b'example parquet bytes'))

    def test_get_detects_size_change_without_hashing(self):
        result=self.complete()
        Path(result['path']).write_bytes(b'changed')
        with patch('downloads.file_hash',side_effect=AssertionError('Polling must not hash')):
            status=self.manager.get(self.task['id'])
        self.assertEqual(status['status'],'failed')
        self.assertEqual(status['error_code'],'file_conflict')

    def test_ready_reuse_checks_hash_without_new_worker(self):
        result=self.complete()
        with patch.object(self.manager,'spawn_worker') as spawn:
            again=self.manager.start(self.task['job_id'],self.task['project'])
        spawn.assert_not_called()
        self.assertEqual(again['id'],result['id'])
        self.assertEqual(again['status'],'ready')

    def test_own_partial_is_removed_before_free_space_check(self):
        folder=safe_folder(self.task['project'],self.task['job_id'])
        leftover=folder/('.xyquant-'+self.task['id']+'-fixture.partial')
        other=folder/('.xyquant-'+'f'*32+'-other.partial')
        leftover.write_bytes(b'incomplete task file');other.write_bytes(b'keep another task')
        checked=[]
        def disk_usage(path):
            checked.append(True)
            self.assertFalse(leftover.exists(),'free-space check must follow cleanup')
            self.assertTrue(other.exists(),'another task partial must remain untouched')
            return type('Space',(),{'free':self.job['bytes']+64*1024**2})()
        with patch('downloads.shutil.disk_usage',side_effect=disk_usage):result=self.complete()
        self.assertEqual(result['status'],'ready')
        self.assertTrue(checked)
        self.assertEqual(other.read_bytes(),b'keep another task')

    def test_disk_full_during_stream_write_is_not_retried_as_network(self):
        errors=[OSError(errno.ENOSPC,'disk full'),OSError('Windows disk full')]
        errors[1].winerror=112
        original_open=Path.open
        async def remote(*args,**kwargs):return self.job
        for write_error in errors:
            with self.subTest(errno=getattr(write_error,'errno',None),winerror=getattr(write_error,'winerror',None)):
                class FullDisk:
                    def __init__(self,stream):self.stream=stream
                    def __enter__(self):return self
                    def __exit__(self,*args):self.stream.close()
                    def write(self,block):raise write_error
                def open_file(path,*args,**kwargs):
                    stream=original_open(path,*args,**kwargs)
                    return FullDisk(stream) if path.suffix=='.partial' and args and args[0]=='xb' else stream
                with patch('downloads.remote_call',remote),patch.object(Path,'open',open_file),patch('downloads.time.sleep') as sleep,self.assertRaises(ClientError) as error:
                    self.manager.perform(self.task)
                self.assertEqual(error.exception.code,'disk_full')
                sleep.assert_not_called()
                self.assertFalse(list(self.project.rglob('*.partial')))

    def test_windows_filename_metacharacters_and_controls_are_rejected(self):
        async def remote(*args,**kwargs):return self.job
        for character in '<>"|?*\x00\x01\n\r\x1f\x7f\x85':
            with self.subTest(character=repr(character)):
                self.job['filename']='factor'+character+'.parquet'
                with patch('downloads.remote_call',remote),self.assertRaises(ClientError) as error:
                    self.manager.perform(self.task)
                self.assertEqual(error.exception.code,'invalid_response')
                self.assertFalse(list(self.project.rglob('*.partial')))


if __name__=='__main__':unittest.main()
