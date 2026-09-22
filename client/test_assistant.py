import concurrent.futures
import hashlib
import io
import json
from pathlib import Path
import tempfile
import time
import unittest
from unittest.mock import patch
from auth_client import AuthClient,ClientError,ORIGIN,crypt
from configuration import configure
from downloads import Downloads,safe_project


class FakeAuth:
    def __init__(self,customer='a'):self.customer=customer
    def identity(self):return {'customer_id':self.customer}
    def access(self):return 'test-only-token'


class AssistantTests(unittest.TestCase):
    def setUp(self):self.temp=tempfile.TemporaryDirectory();self.root=Path(self.temp.name)
    def tearDown(self):self.temp.cleanup()
    def test_dpapi_and_concurrent_refresh(self):
        raw=b'test-only-secret';encrypted=crypt(raw);self.assertNotIn(raw,encrypted);self.assertEqual(crypt(encrypted,True),raw)
        client=AuthClient(self.root)
        client._save(dict(issuer=ORIGIN,customer_id='a',access_token='old',refresh_token='old-refresh',client_id='c',access_expires_at=0,connection_expires_at=time.time()+3600))
        with patch.object(client,'json_request',return_value={'access_token':'new','refresh_token':'new-refresh','expires_in':600}) as request:
            with concurrent.futures.ThreadPoolExecutor(max_workers=5) as pool:values=list(pool.map(lambda _:client.access(),range(5)))
            self.assertEqual(values,['new']*5);self.assertEqual(request.call_count,1)
        self.assertNotIn(b'new-refresh',client.file.read_bytes())
    def test_config_preserve_repeat_conflict_remove(self):
        config=self.root/'config.toml';bridge=self.root/'FactorBridge.exe'
        config.write_text('# existing comment\nmodel="existing"\n[mcp_servers.other]\ncommand="other"\n[mcp_servers.xyquant_factors]\nurl="'+ORIGIN+'/mcp"\nhttp_headers={Authorization="old-test-secret"}\n')
        configure(bridge,config);value=config.read_text();self.assertIn('# existing comment',value);self.assertIn('mcp_servers.other',value);self.assertNotIn('old-test-secret',value)
        configure(bridge,config);self.assertEqual(value,config.read_text())
        configure(bridge,config,remove=True);self.assertNotIn('xyquant_factors',config.read_text());self.assertIn('mcp_servers.other',config.read_text())
        config.write_text('[mcp_servers.xyquant_factors]\nurl="https://other.example/mcp"\n');before=config.read_text()
        with self.assertRaises(ClientError):configure(bridge,config)
        self.assertEqual(before,config.read_text())
    def test_queue_dedup_and_account_isolation(self):
        project=self.root/'中文 研究项目';project.mkdir();auth=FakeAuth();manager=Downloads(self.root/'state',auth)
        with concurrent.futures.ThreadPoolExecutor(max_workers=5) as pool:
            tasks=list(pool.map(lambda _:manager.start('a'*32,str(project),spawn=False),range(5)))
        self.assertEqual(len({t['id'] for t in tasks}),1)
        auth.customer='b'
        with self.assertRaises(ClientError):manager.get(tasks[0]['id'])
        new=manager.start('a'*32,str(project),spawn=False);self.assertNotEqual(new['id'],tasks[0]['id'])
    def prepare(self,body=b'example parquet bytes'):
        project=self.root/'中文 项目';project.mkdir();auth=FakeAuth();auth.opener=type('Opener',(),{'open':lambda _,*a,**kw:io.BytesIO(body)})()
        manager=Downloads(self.root/'state',auth);task=manager.start('a'*32,str(project),spawn=False)
        job=dict(status='ready',oauth_download_url='/mcp/downloads/'+'a'*32,filename='factor.parquet',sha256=hashlib.sha256(body).hexdigest(),bytes=len(body),expires=time.time()+3600)
        return manager,task,job,project
    def test_download_verified_and_no_overwrite(self):
        manager,task,job,project=self.prepare()
        async def remote(*a,**kw):return job
        with patch('downloads.remote_call',remote):manager.perform(task)
        complete=manager.get(task['id']);self.assertEqual(complete['status'],'ready');self.assertEqual(complete['sha256'],job['sha256']);self.assertTrue(Path(complete['path']).is_file())
        self.assertFalse(list(project.rglob('*.partial')))
        Path(complete['path']).write_bytes(b'other data')
        with patch('downloads.remote_call',remote),self.assertRaises(ClientError):manager.perform(task)
        self.assertEqual(Path(complete['path']).read_bytes(),b'other data')
    def test_invalid_paths_disk_full_checksum_and_expiry(self):
        manager,task,job,project=self.prepare()
        with self.assertRaises(ClientError):safe_project('relative/path')
        with self.assertRaises(ClientError):safe_project(str(project/'..'))
        async def remote(*a,**kw):return job
        with patch('downloads.remote_call',remote),patch('downloads.shutil.disk_usage',return_value=type('Space',(),{'free':0})()),self.assertRaises(ClientError):manager.perform(task)
        job['sha256']='0'*64
        with patch('downloads.remote_call',remote),self.assertRaises(ClientError) as error:manager.perform(task)
        self.assertEqual(error.exception.code,'checksum_failed');self.assertFalse(list(project.rglob('*.partial')))
        job['status']='expired'
        with patch('downloads.remote_call',remote),self.assertRaises(ClientError):manager.perform(task)
    def test_restart_keeps_queue_and_marks_running_interrupted(self):
        manager,task,job,project=self.prepare();manager.update(task['id'],status='downloading')
        restored=Downloads(manager.root,manager.auth);restored.run();self.assertEqual(restored.get(task['id'])['status'],'interrupted')
        retry=restored.start(task['job_id'],task['project'],spawn=False);self.assertEqual(retry['id'],task['id']);self.assertEqual(retry['status'],'queued')

    def test_truncated_network_response_retries_whole_file(self):
        manager,task,job,project=self.prepare();bodies=[b'short',b'example parquet bytes']
        def response(*args,**kwargs):return io.BytesIO(bodies.pop(0))
        manager.auth.opener.open=response
        async def remote(*args,**kwargs):return job
        with patch('downloads.remote_call',remote),patch('downloads.time.sleep'):manager.perform(task)
        self.assertEqual(manager.get(task['id'])['status'],'ready');self.assertEqual(bodies,[])


if __name__=='__main__':unittest.main()
