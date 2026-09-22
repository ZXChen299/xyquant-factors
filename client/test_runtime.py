import hashlib
import os
from pathlib import Path
import subprocess
import tempfile
import unittest
from unittest.mock import Mock,patch

from auth_client import ClientError
import runtime


class RuntimeTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.root = Path(self.temp.name)
        self.source = self.root / '插件 程序' / 'FactorBridge.exe'
        self.source.parent.mkdir()
        self.source.write_bytes(b'fixture binary, not executable')
        self.digest = hashlib.sha256(self.source.read_bytes()).hexdigest()
        self.sidecar = self.source.with_suffix('.exe.sha256')
        self.sidecar.write_text(self.digest + '  FactorBridge.exe\n')
        self.state = self.root / '用户 状态'

    def tearDown(self):
        self.temp.cleanup()

    def test_verified_stable_copy_survives_source_removal(self):
        copied = runtime.ensure_runtime(self.state, self.source)
        self.assertEqual(runtime.file_sha256(copied), self.digest)
        self.assertEqual(runtime.ensure_runtime(self.state, self.source), copied)
        self.source.unlink()
        self.assertEqual(runtime.ensure_runtime(self.state, copied), copied)

    def test_mismatch_missing_checksum_and_tampered_copy_rejected(self):
        self.sidecar.unlink()
        with self.assertRaises(ClientError):
            runtime.ensure_runtime(self.state, self.source)
        with self.assertRaises(ClientError):
            runtime.ensure_runtime(self.state, self.source, '0' * 64)
        copied = runtime.ensure_runtime(self.state, self.source, self.digest)
        copied.write_bytes(b'tampered')
        with self.assertRaises(ClientError):
            runtime.ensure_runtime(self.state, self.source, self.digest)

    def test_source_mode_has_hidden_process_and_explicit_root(self):
        with patch('runtime.subprocess.Popen') as popen:
            runtime.spawn_worker('login', ['a' * 32], root=self.state)
        args, options = popen.call_args
        self.assertIn('--login-worker', args[0])
        self.assertIn('--state-root', args[0])
        self.assertEqual(options['stdout'], subprocess.DEVNULL)
        if os.name == 'nt':
            self.assertTrue(options['creationflags'] & subprocess.CREATE_NO_WINDOW)
            self.assertTrue(options['creationflags'] & subprocess.CREATE_BREAKAWAY_FROM_JOB)
        self.assertEqual(options['cwd'], str(self.state))

    def test_frozen_worker_uses_verified_stable_executable(self):
        with patch.object(runtime.sys, 'frozen', True, create=True), patch.object(runtime.sys, 'executable', str(self.source)), patch('runtime.subprocess.Popen') as popen:
            runtime.spawn_worker('download', root=self.state)
        command = popen.call_args.args[0]
        self.assertTrue(Path(command[0]).is_relative_to(self.state / 'runtime'))
        self.assertIn('--worker', command)
        self.assertEqual(popen.call_args.kwargs['env']['PYINSTALLER_RESET_ENVIRONMENT'], '1')
        with self.assertRaises(ValueError):
            runtime.spawn_worker('unknown', root=self.state)

    def test_process_alive_current_and_absent(self):
        self.assertTrue(runtime.process_alive(os.getpid()))
        self.assertFalse(runtime.process_alive(0))
        self.assertFalse(runtime.process_alive(12345678))

    def test_breakaway_denial_uses_normal_host_lifetime_and_reports_it(self):
        denied=OSError('denied');denied.winerror=5
        with patch('runtime.subprocess.Popen',side_effect=[denied,Mock()]) as popen:
            process=runtime.spawn_worker('download',root=self.state)
        self.assertEqual(process.xyquant_lifetime,'host_bound')
        self.assertEqual(popen.call_count,2)
        self.assertFalse(popen.call_args.kwargs['creationflags'] & subprocess.CREATE_BREAKAWAY_FROM_JOB)
        status=runtime.runtime_status(self.state)
        self.assertEqual(status['background_lifetime'],'host_bound')
        self.assertIn('不绕过',status['background_notice'])

    def test_normal_child_denied_is_not_bypassed(self):
        denied=OSError('denied');denied.winerror=5
        with patch('runtime.subprocess.Popen',side_effect=denied) as popen,self.assertRaises(ClientError) as error:
            runtime.spawn_worker('download',root=self.state)
        self.assertEqual(popen.call_count,2)
        self.assertEqual(error.exception.code,'worker_start_failed')


if __name__ == '__main__':
    unittest.main()
