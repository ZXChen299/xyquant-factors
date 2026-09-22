"""Actual Windows job boundaries, without network or production credentials."""
import ctypes
from ctypes import wintypes
import json
import os
from pathlib import Path
import signal
import struct
import subprocess
import sys
import tempfile
import time
import unittest

from runtime import process_alive


LAUNCHER = '''import json,sys,time
from pathlib import Path
import runtime
from auth_client import ClientError
root=Path(sys.argv[1]);gate=root/'go';result=root/'result.json'
deadline=time.monotonic()+15
while not gate.exists() and time.monotonic()<deadline:time.sleep(.02)
real_popen=runtime.subprocess.Popen
def launch(command,**options):
    return real_popen([sys.executable,'-c','import time; time.sleep(60)'],**options)
runtime.subprocess.Popen=launch
try:
    child=runtime.spawn_worker('download',root=root)
    result.write_text(json.dumps(dict(pid=child.pid,lifetime=child.xyquant_lifetime)))
except ClientError as error:
    result.write_text(json.dumps(dict(error=error.code)))
time.sleep(30)
'''


@unittest.skipUnless(os.name=='nt','Windows job semantics')
class RuntimeJobTests(unittest.TestCase):
    def run_boundary(self,allow_breakaway):
        kernel=ctypes.WinDLL('kernel32',use_last_error=True)
        kernel.CreateJobObjectW.argtypes=[ctypes.c_void_p,wintypes.LPCWSTR]
        kernel.CreateJobObjectW.restype=wintypes.HANDLE
        kernel.SetInformationJobObject.argtypes=[wintypes.HANDLE,ctypes.c_int,ctypes.c_void_p,wintypes.DWORD]
        kernel.AssignProcessToJobObject.argtypes=[wintypes.HANDLE,wintypes.HANDLE]
        kernel.CloseHandle.argtypes=[wintypes.HANDLE]
        job=kernel.CreateJobObjectW(None,None)
        self.assertTrue(job)
        # JOBOBJECT_EXTENDED_LIMIT_INFORMATION is 144 bytes on Windows x64.
        limits=ctypes.create_string_buffer(144)
        struct.pack_into('I',limits,16,0x2000|(0x800 if allow_breakaway else 0))
        self.assertTrue(kernel.SetInformationJobObject(job,9,limits,144),ctypes.get_last_error())
        process=None;child_pid=None
        with tempfile.TemporaryDirectory() as directory:
            root=Path(directory)
            try:
                # venv's Windows redirector can spawn its real interpreter before
                # AssignProcessToJobObject; use the actual base interpreter here.
                process=subprocess.Popen([getattr(sys,'_base_executable',sys.executable),'-B','-c',LAUNCHER,str(root)],
                                         cwd=Path(__file__).parent,stdout=subprocess.DEVNULL,stderr=subprocess.PIPE,
                                         creationflags=subprocess.CREATE_NO_WINDOW)
                self.assertTrue(kernel.AssignProcessToJobObject(job,wintypes.HANDLE(int(process._handle))),ctypes.get_last_error())
                (root/'go').write_text('assigned')
                deadline=time.monotonic()+15
                while not (root/'result.json').exists() and time.monotonic()<deadline:time.sleep(.05)
                self.assertTrue((root/'result.json').exists(),'launcher did not report')
                result=json.loads((root/'result.json').read_text())
                child_pid=result.get('pid')
                kernel.CloseHandle(job);job=None
                process.wait(timeout=5)
                if allow_breakaway:
                    self.assertIn('pid',result,result)
                    self.assertEqual(result['lifetime'],'independent')
                    self.assertTrue(process_alive(child_pid),'worker died with the host job')
                else:
                    self.assertEqual(result['lifetime'],'host_bound')
                    deadline=time.monotonic()+5
                    while process_alive(child_pid) and time.monotonic()<deadline:time.sleep(.05)
                    self.assertFalse(process_alive(child_pid),'normal child must remain subject to its host job')
            finally:
                if job:kernel.CloseHandle(job)
                if process:
                    if process.poll() is None:process.kill();process.wait(timeout=5)
                    if process.stderr:process.stderr.close()
                if child_pid and process_alive(child_pid):
                    os.kill(child_pid,signal.SIGTERM)

    def test_allowed_job_worker_outlives_parent_job(self):
        self.run_boundary(True)

    def test_forbidden_breakaway_reports_host_bound_and_obeys_job_exit(self):
        self.run_boundary(False)


if __name__=='__main__':unittest.main()
