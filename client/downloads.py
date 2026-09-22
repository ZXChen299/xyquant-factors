"""Local durable download queue. It never reads factor contents or creates cloud exports."""
import asyncio
import contextlib
import errno
import hashlib
import http.client
import json
import os
from pathlib import Path
import re
import secrets
import shutil
import sqlite3
import stat
import subprocess
import sys
import threading
import time
import urllib.error
import urllib.request
from auth_client import AuthClient,ClientError,ORIGIN,app_dir,mutex
from remote import remote_call
from runtime import process_alive,runtime_status,spawn_worker


def safe_project(value):
    path=Path(value)
    if not path.is_absolute() or str(path).startswith(('\\\\','//')) or not path.is_dir():
        raise ClientError('project_dir 必须是当前研究项目已存在的本地绝对目录。','invalid_path')
    if '..' in path.parts:raise ClientError('项目路径不能包含上级跳转。','invalid_path')
    for part in (path,*path.parents):
        if part.exists() and (part.is_symlink() or getattr(part.lstat(),'st_file_attributes',0)&0x400):
            raise ClientError('下载目录不能经过符号链接或目录联接。','invalid_path')
    return path.resolve()


def safe_folder(project,job_id):
    root=safe_project(str(project));folder=root/'downloads'/'factors'/job_id
    if not re.fullmatch('[a-f0-9]{32}',job_id):raise ClientError('任务编号无效。')
    for part in (root/'downloads',root/'downloads'/'factors',folder):
        if part.exists() and (part.is_symlink() or getattr(part.lstat(),'st_file_attributes',0)&0x400 or not part.is_dir()):
            raise ClientError('下载目录存在链接或同名文件。','invalid_path')
        part.mkdir(exist_ok=True)
    if not folder.resolve().is_relative_to(root):raise ClientError('下载目录超出项目。','invalid_path')
    return folder


def file_hash(path):
    digest=hashlib.sha256()
    with path.open('rb') as stream:
        for block in iter(lambda:stream.read(1024*1024),b''):digest.update(block)
    return digest.hexdigest()


class Downloads:
    def __init__(self,root=None,auth=None):
        self.root=Path(root) if root else app_dir();self.root.mkdir(parents=True,exist_ok=True)
        self.auth=auth or AuthClient(self.root);self.database=self.root/'downloads.sqlite'
        with self.db() as db:
            db.executescript('''PRAGMA journal_mode=WAL;
            CREATE TABLE IF NOT EXISTS downloads(id TEXT PRIMARY KEY,customer_id TEXT NOT NULL,job_id TEXT NOT NULL,
              project TEXT NOT NULL,fingerprint TEXT UNIQUE NOT NULL,status TEXT NOT NULL,created REAL NOT NULL,updated REAL NOT NULL,
              bytes INTEGER NOT NULL DEFAULT 0,total INTEGER,path TEXT,sha256 TEXT,error TEXT,error_code TEXT);
            CREATE TABLE IF NOT EXISTS download_worker(id INTEGER PRIMARY KEY CHECK(id=1),pid INTEGER NOT NULL,heartbeat REAL NOT NULL);
            ''')
    @contextlib.contextmanager
    def db(self):
        db=sqlite3.connect(self.database,timeout=20);db.row_factory=sqlite3.Row
        try:db.execute('BEGIN IMMEDIATE');yield db;db.commit()
        except Exception:db.rollback();raise
        finally:db.close()
    def update(self,identity,**values):
        if not set(values)<={'status','bytes','total','path','sha256','error','error_code'}:raise ValueError('Invalid local state')
        values['updated']=time.time()
        with self.db() as db:db.execute('UPDATE downloads SET '+','.join(k+'=?' for k in values)+' WHERE id=?',(*values.values(),identity))
    def get(self,identity):
        customer=self.auth.identity()['customer_id']
        self.recover()
        with self.db() as db:row=db.execute('SELECT * FROM downloads WHERE id=? AND customer_id=?',(identity,customer)).fetchone()
        if not row:raise ClientError('本地下载任务不存在。','not_found')
        if row['status']=='ready':
            issue=self.ready_issue(row)
            if issue:
                self.invalidate_ready(row,issue)
                with self.db() as db:row=db.execute('SELECT * FROM downloads WHERE id=? AND customer_id=?',(identity,customer)).fetchone()
        result=dict(row);result.pop('fingerprint',None);result.update(runtime_status(self.root));return result
    def invalidate_ready(self,row,issue):
        with self.db() as db:
            db.execute("UPDATE downloads SET status='failed',error_code=?,error=?,updated=? WHERE id=? AND status='ready' AND updated=?",(issue[0],issue[1],time.time(),row['id'],row['updated']))
    def ready_issue(self,row,verify_hash=False):
        """Polling is cheap; a new request reusing a ready file also verifies its hash."""
        try:
            path=Path(row['path']) if row['path'] else None
            if path is None or not path.exists():return 'file_missing','已下载文件已被移动或删除，请重新调用 download_export。'
            project=safe_project(row['project'])
            if not path.is_absolute() or path.parent!=project/'downloads'/'factors'/row['job_id']:
                return 'invalid_path','本地文件位置不符合任务目录，未读取或覆盖文件。'
            for part in (path,*path.parents):
                if part.is_symlink() or getattr(part.lstat(),'st_file_attributes',0)&0x400:
                    return 'invalid_path','本地文件或目录已替换为链接，未读取或覆盖文件。'
            if not path.is_file():return 'invalid_path','本地下载文件已替换为其他类型，未覆盖。'
            if path.stat().st_size!=row['total'] or (verify_hash and file_hash(path)!=row['sha256']):
                return 'file_conflict','本地文件已改变，未覆盖；请移动该文件后重新下载。'
        except (ClientError,OSError,ValueError,TypeError):
            return 'invalid_path','无法安全访问原下载文件，请检查项目目录。'
        return None
    def recover(self):
        """A dead worker must not leave the conversation polling forever."""
        with self.db() as db:
            worker=db.execute('SELECT pid,heartbeat FROM download_worker WHERE id=1').fetchone()
            pending=db.execute("SELECT 1 FROM downloads WHERE status IN ('queued','waiting','downloading','verifying') LIMIT 1").fetchone()
        if not pending:return
        if worker and time.time()-worker['heartbeat']<30 and process_alive(worker['pid']):return
        try:
            # Also respects the old assistant worker, which has no heartbeat table.
            with mutex('download-worker',timeout=0,root=self.root):
                now=time.time()
                with self.db() as db:
                    db.execute("UPDATE downloads SET status='interrupted',error='下载进程中断，请重新调用 download_export。',error_code='interrupted',updated=? WHERE status IN ('waiting','downloading','verifying')",(now,))
                    db.execute("UPDATE downloads SET status='interrupted',error='下载后台进程未能启动，请重新调用 download_export。',error_code='worker_start_failed',updated=? WHERE status='queued' AND updated<?",(now,now-30))
                    db.execute('DELETE FROM download_worker')
        except ClientError as error:
            if error.code!='busy':raise
    def start(self,job_id,project,spawn=True):
        if not re.fullmatch('[a-f0-9]{32}',job_id):raise ClientError('任务编号无效。')
        project=str(safe_project(project));customer=self.auth.identity()['customer_id']
        fingerprint=hashlib.sha256(json.dumps([customer,job_id,os.path.normcase(project)]).encode()).hexdigest()
        self.recover()
        with self.db() as db:existing=db.execute('SELECT * FROM downloads WHERE fingerprint=?',(fingerprint,)).fetchone()
        if existing and existing['status']=='ready':
            issue=self.ready_issue(existing,verify_hash=True)
            if not issue:return self.get(existing['id'])
            self.invalidate_ready(existing,issue)
            if issue[0]!='file_missing':return self.get(existing['id'])
        should_spawn=True
        with self.db() as db:
            row=db.execute('SELECT * FROM downloads WHERE fingerprint=?',(fingerprint,)).fetchone()
            if row:
                identity=row['id']
                if row['status'] in ('failed','interrupted'):
                    db.execute("UPDATE downloads SET status='queued',error=NULL,error_code=NULL,bytes=0,updated=? WHERE id=?",(time.time(),identity))
                elif row['status']!='queued':should_spawn=False
            else:
                identity=secrets.token_hex(16);now=time.time()
                db.execute('INSERT INTO downloads(id,customer_id,job_id,project,fingerprint,status,created,updated) VALUES(?,?,?,?,?,?,?,?)',
                    (identity,customer,job_id,project,fingerprint,'queued',now,now))
        if spawn and should_spawn:
            try:self.spawn_worker()
            except ClientError as error:self.update(identity,status='failed',error=str(error),error_code=error.code)
        return self.get(identity)
    def spawn_worker(self):
        spawn_worker('download',root=self.root)
    def run(self):
        try:
            with mutex('download-worker',timeout=10,root=self.root):
                with self.db() as db:
                    db.execute("UPDATE downloads SET status='interrupted',error='下载进程中断，请重新调用 download_export。',error_code='interrupted' WHERE status IN ('waiting','downloading','verifying')")
                    db.execute('INSERT OR REPLACE INTO download_worker VALUES(1,?,?)',(os.getpid(),time.time()))
                stopped=threading.Event()
                def heartbeat():
                    while not stopped.wait(3):
                        try:
                            with self.db() as db:db.execute('UPDATE download_worker SET heartbeat=? WHERE id=1 AND pid=?',(time.time(),os.getpid()))
                        except sqlite3.Error:return
                thread=threading.Thread(target=heartbeat,daemon=True);thread.start()
                try:
                    while True:
                        with self.db() as db:row=db.execute("SELECT * FROM downloads WHERE status='queued' ORDER BY created LIMIT 1").fetchone()
                        if not row:return
                        try:self.perform(dict(row))
                        except ClientError as error:self.update(row['id'],status='failed',error=str(error),error_code=error.code)
                        except Exception:self.update(row['id'],status='failed',error='本地下载中断，请重试。',error_code='download_failed')
                finally:
                    stopped.set();thread.join(timeout=4)
                    with self.db() as db:db.execute('DELETE FROM download_worker WHERE id=1 AND pid=?',(os.getpid(),))
        except ClientError as error:
            if error.code!='busy':raise
    def check_identity(self,row):
        if self.auth.identity()['customer_id']!=row['customer_id']:raise ClientError('当前登录账号已变化，请切回创建任务的账号。','account_changed')
    def perform(self,row):
        self.check_identity(row);self.update(row['id'],status='waiting');deadline=time.monotonic()+2100
        while True:
            self.check_identity(row)
            job=asyncio.run(remote_call('get_export',dict(job_id=row['job_id']),self.auth))
            if job['status']=='ready':break
            if job['status'] not in ('queued','running'):raise ClientError(job.get('error') or '云端文件已过期，请重新创建导出。',job.get('error_code') or 'export_expired')
            if time.monotonic()>deadline:raise ClientError('等待导出超时，云端任务未被取消。','wait_timeout')
            time.sleep(3)
        expected='/mcp/downloads/'+row['job_id']
        if job.get('oauth_download_url')!=expected:raise ClientError('下载地址校验失败。','invalid_response')
        filename=job.get('filename','')
        if not isinstance(filename,str) or not filename or filename.endswith(('.', ' ')) or any(c in filename for c in '/\\:<>"|?*') or any(ord(c)<32 or 127<=ord(c)<=159 for c in filename) or Path(filename).name!=filename or re.match(r'(?i)^(con|prn|aux|nul|com[1-9]|lpt[1-9])(?:\.|$)',filename):
            raise ClientError('服务端文件名无效。','invalid_response')
        if not re.fullmatch('[a-f0-9]{64}',job.get('sha256','')) or not isinstance(job.get('bytes'),int) or not 0<=job['bytes']<=1024**3:
            raise ClientError('文件信息校验失败。','invalid_response')
        folder=safe_folder(row['project'],row['job_id']);destination=folder/filename
        if destination.exists():
            if destination.is_symlink() or not destination.is_file() or getattr(destination.lstat(),'st_file_attributes',0)&0x400:raise ClientError('目标文件是链接或目录。','invalid_path')
            if destination.stat().st_size==job['bytes'] and file_hash(destination)==job['sha256']:
                self.update(row['id'],status='ready',path=str(destination),bytes=job['bytes'],total=job['bytes'],sha256=job['sha256']);return
            raise ClientError('目标文件已存在且内容不同，未覆盖。','file_conflict')
        # Remove only partial files generated for this specific local task after an interrupted run.
        for previous in folder.glob('.xyquant-'+row['id']+'-*.partial'):
            if previous.is_file() and not previous.is_symlink() and not (getattr(previous.lstat(),'st_file_attributes',0)&0x400):previous.unlink()
        if shutil.disk_usage(folder).free<job['bytes']+64*1024**2:raise ClientError('本地磁盘空间不足。','disk_full')
        partial=folder/('.xyquant-'+row['id']+'-'+secrets.token_hex(8)+'.partial')
        try:
            for attempt in range(3):
                self.check_identity(row)
                if job['expires']<=time.time():raise ClientError('云端文件已过期，请重新导出。','export_expired')
                partial.unlink(missing_ok=True);self.update(row['id'],status='downloading',total=job['bytes'],bytes=0)
                digest=hashlib.sha256();size=0
                try:
                    token=self.auth.access()
                    request=urllib.request.Request(ORIGIN+expected,headers={'Authorization':'Bearer '+token})
                    with self.auth.opener.open(request,timeout=60) as response,partial.open('xb') as stream:
                        last=0
                        while True:
                            block=response.read(1024*1024)
                            if not block:break
                            size+=len(block)
                            if size>job['bytes']:raise ClientError('下载文件超出声明大小。','checksum_failed')
                            stream.write(block);digest.update(block)
                            if time.monotonic()-last>1:self.update(row['id'],bytes=size);last=time.monotonic();self.check_identity(row)
                    if size!=job['bytes']:raise urllib.error.URLError('Incomplete response')
                    if digest.hexdigest()!=job['sha256']:raise ClientError('文件 SHA-256 校验不符。','checksum_failed')
                    break
                except urllib.error.HTTPError as error:
                    if error.code==401:
                        self.auth.invalidate(token)
                        raise ClientError('连接授权已失效，请在对话中重新登录。','login_required') from None
                    if error.code==403:raise ClientError('当前账号没有此文件的数据权限，请联系管理员。','permission_denied') from None
                    if error.code==404:raise ClientError('文件不存在、已过期或不属于当前客户。','export_expired') from None
                    if error.code not in (429,503) or attempt==2:raise ClientError('下载服务繁忙，请稍后重试。','busy') from None
                except (urllib.error.URLError,http.client.IncompleteRead,TimeoutError,OSError) as error:
                    if getattr(error,'errno',None)==errno.ENOSPC or getattr(error,'winerror',None)==112:
                        raise ClientError('本地磁盘空间不足，未完成文件已清理。请释放空间后重试。','disk_full') from None
                    if attempt==2:raise ClientError('网络或本地磁盘写入失败，请检查后重试。','download_interrupted') from None
                time.sleep((5,15,30)[attempt])
            self.update(row['id'],status='verifying',bytes=size)
            self.check_identity(row);safe_folder(row['project'],row['job_id'])
            # Windows rename fails if a destination appeared concurrently; never overwrite.
            partial.rename(destination)
            self.update(row['id'],status='ready',path=str(destination),sha256=job['sha256'],bytes=size,total=size)
        finally:partial.unlink(missing_ok=True)
