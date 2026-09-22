"""Short MCP calls backed by a single durable per-user browser-login task."""
import contextlib
import json
import os
from pathlib import Path
import re
import secrets
import sqlite3
import threading
import time

from auth_client import AuthClient, ClientError, app_dir, mutex
from runtime import process_alive, runtime_status, spawn_worker

ACTIVE = ('preparing', 'waiting_authorization')


class LoginTasks:
    def __init__(self, root=None, auth=None):
        self.root = Path(root or app_dir())
        self.root.mkdir(parents=True, exist_ok=True)
        self.auth = auth or AuthClient(self.root)
        self.database = self.root / 'login_tasks.sqlite'
        with self.db() as db:
            db.executescript('''PRAGMA journal_mode=WAL;
            CREATE TABLE IF NOT EXISTS login_tasks(
                id TEXT PRIMARY KEY, status TEXT NOT NULL, created REAL NOT NULL,
                expires REAL NOT NULL, updated REAL NOT NULL, worker_pid INTEGER,
                authorization_url TEXT, identity_json TEXT, error TEXT, error_code TEXT);
            ''')

    @contextlib.contextmanager
    def db(self):
        db = sqlite3.connect(self.database, timeout=20)
        db.row_factory = sqlite3.Row
        try:
            db.execute('BEGIN IMMEDIATE')
            yield db
            db.commit()
        except Exception:
            db.rollback()
            raise
        finally:
            db.close()

    def _recover(self, db):
        now = time.time()
        for row in db.execute("SELECT * FROM login_tasks WHERE status IN ('preparing','waiting_authorization')").fetchall():
            if row['expires'] <= now:
                status, code, message = 'expired', 'login_timeout', '登录等待已超时，请重新发起登录。'
            elif ((row['worker_pid'] and not process_alive(row['worker_pid'])) or
                  now - row['updated'] > 30):
                status, code, message = 'interrupted', 'login_interrupted', '登录后台进程已中断，请重新发起登录。'
            else:
                continue
            db.execute('UPDATE login_tasks SET status=?,error_code=?,error=?,authorization_url=NULL,updated=? WHERE id=?',
                       (status, code, message, now, row['id']))

    def status(self):
        """Local state only. Cloud requests independently revalidate the connection."""
        runtime=runtime_status(self.root)
        try:
            identity = self.auth.identity()
        except ClientError as error:
            if error.code != 'login_required':
                raise
            return dict(status='login_required', connected=False, verified_by_server=False,
                        message='尚未连接因子账号，请调用 start_login。',**runtime)
        if (identity.get('connection_expires_at') or 0) <= time.time():
            return dict(status='expired', connected=False, verified_by_server=False,
                        message='本地记录的授权已到期，请调用 start_login。',**runtime)
        return dict(status='connected', connected=True, verified_by_server=False,
                    **runtime,
                    **{key: identity.get(key) for key in
                       ('customer_id', 'username', 'connection_id', 'connection_expires_at')})

    def _public(self, row):
        result = dict(login_id=row['id'], status=row['status'], created_at=row['created'],
                      expires_at=row['expires'],**runtime_status(self.root))
        if row['status'] == 'waiting_authorization' and row['authorization_url']:
            result['authorization_url'] = row['authorization_url']
            result['message'] = '请点击授权链接，在网站登录并确认授权，然后返回 Codex。'
        elif row['status'] == 'preparing':
            result['message'] = '正在准备网页登录，请稍后查询 get_login_status。'
        elif row['status'] == 'connected':
            result['message'] = '登录授权已完成，可以继续查询或下载因子。'
            result['identity'] = json.loads(row['identity_json'] or '{}')
        if row['error_code']:
            result.update(error=row['error'], error_code=row['error_code'])
        return result

    def get(self, login_id):
        if not isinstance(login_id, str) or not re.fullmatch('[a-f0-9]{32}', login_id):
            raise ClientError('登录任务不存在。', 'not_found')
        with self.db() as db:
            self._recover(db)
            row = db.execute('SELECT * FROM login_tasks WHERE id=?', (login_id,)).fetchone()
        if row is None:
            raise ClientError('登录任务不存在。', 'not_found')
        return self._public(row)

    def start(self, spawn=True):
        with mutex('login-tasks', root=self.root):
            local = self.status()
            if local['connected']:
                return {**local, 'message': '已有本地连接，将复用当前账号；服务端会核验每次请求。'}
            with self.db() as db:
                self._recover(db)
                row = db.execute("SELECT * FROM login_tasks WHERE status IN ('preparing','waiting_authorization') ORDER BY created DESC LIMIT 1").fetchone()
                if row:
                    return self._public(row)
                now = time.time()
                login_id = secrets.token_hex(16)
                db.execute('INSERT INTO login_tasks(id,status,created,expires,updated) VALUES(?,?,?,?,?)',
                           (login_id, 'preparing', now, now + 300, now))
                # Login links are transient public authorization requests, never credentials.
                db.execute('DELETE FROM login_tasks WHERE expires<?', (now - 86400,))
            if spawn:
                try:
                    process = spawn_worker('login', [login_id], root=self.root)
                    with self.db() as db:
                        db.execute("UPDATE login_tasks SET worker_pid=? WHERE id=? AND worker_pid IS NULL AND status IN ('preparing','waiting_authorization')", (process.pid, login_id))
                except ClientError as error:
                    self._finish(login_id, 'failed', error=str(error), error_code=error.code)
            return self.get(login_id)

    def _finish(self, login_id, status, identity=None, error=None, error_code=None):
        safe_identity = {key: identity.get(key) for key in
                         ('customer_id', 'username', 'connection_id', 'connection_expires_at')} if identity else None
        with self.db() as db:
            db.execute("UPDATE login_tasks SET status=?,identity_json=?,error=?,error_code=?,authorization_url=NULL,updated=? WHERE id=? AND status IN ('preparing','waiting_authorization')",
                       (status, json.dumps(safe_identity) if safe_identity else None,
                        error, error_code, time.time(), login_id))

    def _cancelled(self, login_id):
        with self.db() as db:
            row = db.execute('SELECT status,expires FROM login_tasks WHERE id=?', (login_id,)).fetchone()
        return not row or row['status'] not in ACTIVE or row['expires'] <= time.time()

    def run(self, login_id):
        if not isinstance(login_id, str) or not re.fullmatch('[a-f0-9]{32}', login_id):
            return
        try:
            with mutex('login-worker', timeout=1, root=self.root):
                with self.db() as db:
                    row = db.execute('SELECT * FROM login_tasks WHERE id=?', (login_id,)).fetchone()
                    if not row or row['status'] not in ACTIVE or row['expires'] <= time.time():
                        self._recover(db)
                        return
                    db.execute('UPDATE login_tasks SET worker_pid=?,updated=? WHERE id=?', (os.getpid(), time.time(), login_id))
                    expires = row['expires']
                stopped = threading.Event()

                def heartbeat():
                    while not stopped.wait(3):
                        try:
                            with self.db() as db:
                                db.execute("UPDATE login_tasks SET updated=? WHERE id=? AND status IN ('preparing','waiting_authorization')", (time.time(), login_id))
                        except sqlite3.Error:
                            return

                def on_ready(url):
                    with self.db() as db:
                        db.execute("UPDATE login_tasks SET status='waiting_authorization',authorization_url=?,updated=? WHERE id=? AND status='preparing'", (url, time.time(), login_id))

                thread = threading.Thread(target=heartbeat, daemon=True)
                thread.start()
                try:
                    identity = self.auth.login(open_browser=None, on_ready=on_ready,
                                               cancelled=lambda: self._cancelled(login_id),
                                               timeout=max(0, expires - time.time()))
                    self._finish(login_id, 'connected', identity=identity)
                except ClientError as error:
                    status = {'login_cancelled': 'cancelled', 'login_timeout': 'expired'}.get(error.code, 'failed')
                    if time.time() >= expires:
                        status, error = 'expired', ClientError('登录等待已超时，请重新发起登录。', 'login_timeout')
                    self._finish(login_id, status, error=str(error), error_code=error.code)
                except Exception:
                    self._finish(login_id, 'failed', error='登录过程未完成，请重新发起登录。', error_code='login_failed')
                finally:
                    stopped.set()
                    thread.join(timeout=4)
        except ClientError as error:
            if error.code != 'busy':
                raise

    def disconnect(self):
        with mutex('login-tasks', root=self.root):
            with self.db() as db:
                db.execute("UPDATE login_tasks SET status='cancelled',authorization_url=NULL,error='连接已断开，登录已取消。',error_code='login_cancelled',updated=? WHERE status IN ('preparing','waiting_authorization')", (time.time(),))
            # A pending login checks its cancelled state inside the credential lock before saving.
            self.auth.disconnect()
        return dict(status='disconnected', connected=False, message='当前连接已断开，本地凭据已清理。')
