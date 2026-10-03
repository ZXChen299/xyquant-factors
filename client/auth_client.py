"""Browser OAuth + per-Windows-user encrypted credentials. Never expose tokens to tools."""
import base64
import contextlib
import ctypes
from ctypes import wintypes
import hashlib
import http.server
import json
import os
from pathlib import Path
import secrets
import threading
import time
import urllib.error
import urllib.parse
import urllib.request
import webbrowser

ORIGIN='https://47.103.215.251'
RESOURCE=ORIGIN+'/mcp'
VERSION='0.2.0-rc.2'
SCOPES='factors:read factors:export factors:download research:read'


class ClientError(Exception):
    def __init__(self,message,code='client_error'):super().__init__(message);self.code=code


def app_dir():
    return Path(os.environ.get('LOCALAPPDATA',str(Path.home()/'AppData'/'Local')))/'XYQuant'/'FactorConnect'


@contextlib.contextmanager
def mutex(name,timeout=60,root=None):
    if os.name!='nt':raise ClientError('因子插件首版仅支持 Windows。')
    kernel=ctypes.WinDLL('kernel32',use_last_error=True)
    kernel.CreateMutexW.argtypes=[ctypes.c_void_p,wintypes.BOOL,wintypes.LPCWSTR];kernel.CreateMutexW.restype=wintypes.HANDLE
    kernel.WaitForSingleObject.argtypes=[wintypes.HANDLE,wintypes.DWORD];kernel.WaitForSingleObject.restype=wintypes.DWORD
    kernel.ReleaseMutex.argtypes=[wintypes.HANDLE];kernel.CloseHandle.argtypes=[wintypes.HANDLE]
    # Include the per-user directory, so another Windows account has its own lock namespace.
    identity=hashlib.sha256(str(Path(root) if root else app_dir()).lower().encode()).hexdigest()[:24]
    handle=kernel.CreateMutexW(None,False,'Local\\XYQuant-'+identity+'-'+name)
    if not handle:raise ClientError('无法创建本地互斥锁。')
    result=kernel.WaitForSingleObject(handle,int(timeout*1000))
    try:
        if result not in (0,0x80):raise ClientError('另一个连接操作正在进行，请稍后重试。','busy')
        yield
    finally:
        if result in (0,0x80):kernel.ReleaseMutex(handle)
        kernel.CloseHandle(handle)


class Blob(ctypes.Structure):
    _fields_=[('size',wintypes.DWORD),('data',ctypes.POINTER(ctypes.c_byte))]


def crypt(data,decrypt=False):
    if os.name!='nt':raise ClientError('凭据加密需要 Windows。')
    raw=ctypes.create_string_buffer(data);source=Blob(len(data),ctypes.cast(raw,ctypes.POINTER(ctypes.c_byte)));result=Blob()
    dll=ctypes.WinDLL('crypt32',use_last_error=True)
    fn=dll.CryptUnprotectData if decrypt else dll.CryptProtectData
    fn.argtypes=[ctypes.POINTER(Blob),ctypes.c_void_p,ctypes.c_void_p,ctypes.c_void_p,ctypes.c_void_p,wintypes.DWORD,ctypes.POINTER(Blob)]
    fn.restype=wintypes.BOOL
    if not fn(ctypes.byref(source),None,None,None,None,1,ctypes.byref(result)):
        raise ClientError('无法读取此 Windows 用户的登录状态，请重新登录。','login_required')
    try:return ctypes.string_at(result.data,result.size)
    finally:
        kernel=ctypes.WinDLL('kernel32');kernel.LocalFree.argtypes=[ctypes.c_void_p];kernel.LocalFree(result.data)


class NoRedirect(urllib.request.HTTPRedirectHandler):
    def redirect_request(self,*args,**kwargs):return None


class AuthClient:
    def __init__(self,root=None):
        self.root=Path(root) if root else app_dir();self.root.mkdir(parents=True,exist_ok=True)
        self.file=self.root/'credentials.dpapi'
        self.opener=urllib.request.build_opener(urllib.request.ProxyHandler({}),NoRedirect())

    def _read(self):
        if not self.file.exists():raise ClientError('尚未连接因子账号，请调用 start_login 在浏览器登录授权。','login_required')
        try:data=json.loads(crypt(self.file.read_bytes(),True))
        except (OSError,ValueError,TypeError):raise ClientError('登录状态损坏，请重新登录。','login_required') from None
        if not isinstance(data,dict):raise ClientError('登录状态损坏，请重新登录。','login_required')
        if data.get('issuer')!=ORIGIN:raise ClientError('登录状态的服务地址不匹配。','login_required')
        return data

    def _save(self,data):
        temporary=self.file.with_suffix('.'+secrets.token_hex(6)+'.tmp')
        try:temporary.write_bytes(crypt(json.dumps(data).encode()));temporary.replace(self.file)
        finally:temporary.unlink(missing_ok=True)

    def json_request(self,path,data=None,token=None,form=False):
        headers={'Accept':'application/json'};body=None
        if data is not None:
            body=(urllib.parse.urlencode(data) if form else json.dumps(data)).encode()
            headers['Content-Type']='application/x-www-form-urlencoded' if form else 'application/json'
        if token:headers['Authorization']='Bearer '+token
        try:
            with self.opener.open(urllib.request.Request(ORIGIN+path,data=body,headers=headers),timeout=45) as response:
                raw=response.read();return json.loads(raw) if raw else {}
        except urllib.error.HTTPError as error:
            oauth_error=None
            try:
                payload=json.loads(error.read(4096));oauth_error=payload.get('error') if isinstance(payload,dict) else None
            except (ValueError,OSError):pass
            if error.code==401 or (path=='/factors/oauth/token' and oauth_error in ('invalid_grant','invalid_client')):
                raise ClientError('登录授权已失效，请重新登录。','login_required') from None
            if error.code==403:raise ClientError('当前账号无权执行此操作，请检查授权或联系管理员。','permission_denied') from None
            if error.code==400:raise ClientError('请求参数未获服务端接受，请检查条件后重试。','invalid_request') from None
            if error.code in (429,503):raise ClientError('服务器繁忙，请稍后重试。','busy') from None
            raise ClientError('服务请求失败，HTTP '+str(error.code),'network_error') from None
        except (urllib.error.URLError,TimeoutError,OSError):raise ClientError('网络连接失败，请检查网络后重试。','network_error') from None
        except (ValueError,UnicodeError):raise ClientError('服务器返回了无效响应。','invalid_response') from None

    def identity(self):
        with mutex('credentials',root=self.root):
            data=self._read()
            return {k:data.get(k) for k in ('customer_id','username','connection_id','connection_expires_at')}

    def access(self,force=False):
        with mutex('credentials',root=self.root):
            data=self._read()
            if data.get('connection_expires_at',0)<=time.time():raise ClientError('连接授权已到期，请重新登录。','login_required')
            if not force and data.get('access_expires_at',0)>time.time()+90:return data['access_token']
            try:updated=self.json_request('/factors/oauth/token',dict(grant_type='refresh_token',refresh_token=data['refresh_token'],client_id=data['client_id'],resource=RESOURCE),form=True)
            except ClientError as error:
                if error.code=='login_required':self.file.unlink(missing_ok=True)
                raise
            data.update(updated);data['access_expires_at']=time.time()+updated['expires_in'];self._save(data)
            return data['access_token']

    def invalidate(self,token=None):
        """Best-effort local cleanup; server rejection does not wait for a refresh lock."""
        try:
            with mutex('credentials',timeout=0,root=self.root):
                if token is not None:
                    try:data=self._read()
                    except ClientError as error:
                        if error.code=='login_required':return
                        raise
                    if data.get('access_token')!=token:return
                self.file.unlink(missing_ok=True)
        except ClientError as error:
            if error.code=='busy':return
            raise

    def login(self,open_browser=webbrowser.open,on_ready=None,cancelled=None,timeout=300):
        """Authorize in a browser; open_browser=None leaves opening the link to the user."""
        deadline=time.monotonic()+max(0,min(float(timeout),300))
        def check_cancelled():
            if cancelled and cancelled():raise ClientError('已取消登录。','login_cancelled')
            if time.monotonic()>=deadline:raise ClientError('登录等待已超时，请重新发起登录。','login_timeout')
        with mutex('login',timeout=1,root=self.root):
            check_cancelled()
            verifier=secrets.token_urlsafe(48);state=secrets.token_urlsafe(32);result={};finished=threading.Event()
            callback='/callback/'+secrets.token_urlsafe(16)
            class Handler(http.server.BaseHTTPRequestHandler):
                def log_message(self,*args):pass
                def do_GET(self):
                    if finished.is_set():self.send_error(409,'Callback already used');return
                    parsed=urllib.parse.urlsplit(self.path);params=urllib.parse.parse_qs(parsed.query)
                    good=parsed.path==callback and params.get('state')==[state] and params.get('iss')==[ORIGIN]
                    if not good:self.send_error(400,'Invalid callback');return
                    if params.get('error'):result['error']=True
                    elif len(params.get('code',[]))==1:result['code']=params['code'][0]
                    else:self.send_error(400,'Missing code');return
                    text='已收到授权，请返回 Codex 查看连接结果；若对话已结束，请说“继续”。' if 'code' in result else '已取消连接，请返回 Codex。'
                    body=('<!doctype html><meta charset="utf-8"><title>XYQuant 因子</title><h2>'+text+'</h2>').encode()
                    finished.set()
                    self.send_response(200);self.send_header('Content-Type','text/html; charset=utf-8');self.send_header('Cache-Control','no-store');self.send_header('Referrer-Policy','no-referrer');self.send_header('Content-Length',str(len(body)));self.end_headers()
                    try:self.wfile.write(body)
                    except (BrokenPipeError,ConnectionResetError):pass
            class CallbackServer(http.server.HTTPServer):
                def get_request(self):
                    connection,address=super().get_request()
                    connection.settimeout(2)
                    return connection,address
            server=CallbackServer(('127.0.0.1',0),Handler);server.timeout=1
            redirect='http://127.0.0.1:'+str(server.server_port)+callback
            try:
                client=self.json_request('/factors/oauth/register',dict(client_name='XYQuant 因子插件 Windows',application_type='native',redirect_uris=[redirect],token_endpoint_auth_method='none'))
                check_cancelled()
                params=dict(client_id=client['client_id'],redirect_uri=redirect,response_type='code',scope=SCOPES,state=state,resource=RESOURCE,
                    code_challenge_method='S256',code_challenge=base64.urlsafe_b64encode(hashlib.sha256(verifier.encode()).digest()).decode().rstrip('='))
                url=ORIGIN+'/factors/oauth/authorize?'+urllib.parse.urlencode(params)
                if on_ready:on_ready(url)
                if open_browser is not None and not open_browser(url):raise ClientError('无法打开浏览器，请点击对话中的授权链接。','browser_unavailable')
                while not finished.is_set():
                    check_cancelled();server.handle_request()
                check_cancelled()
                if 'code' not in result:raise ClientError('已取消登录，请重新发起授权。','login_cancelled')
                server.server_close()
                data=self.json_request('/factors/oauth/token',dict(grant_type='authorization_code',client_id=client['client_id'],redirect_uri=redirect,code=result['code'],code_verifier=verifier,resource=RESOURCE),form=True)
                data.update(issuer=ORIGIN,client_id=client['client_id'],access_expires_at=time.time()+data['expires_in'])
                with mutex('credentials',root=self.root):
                    # disconnect marks the task cancelled before it takes this same lock.
                    if cancelled and cancelled():
                        try:self.json_request('/factors/oauth/revoke',dict(token=data['refresh_token'],client_id=data['client_id']),form=True)
                        except ClientError:pass
                        raise ClientError('已取消登录。','login_cancelled')
                    try:previous=self._read()
                    except ClientError:previous=None
                    if previous:
                        try:self.json_request('/factors/oauth/revoke',dict(token=previous['refresh_token'],client_id=previous['client_id']),form=True)
                        except ClientError:pass
                    self._save(data)
                return self.identity()
            finally:server.server_close()

    def disconnect(self):
        with mutex('credentials',root=self.root):
            try:data=self._read()
            except ClientError:self.file.unlink(missing_ok=True);return
            # If offline, keep the credentials so a later disconnect can revoke the server grant.
            self.json_request('/factors/oauth/revoke',dict(token=data['refresh_token'],client_id=data['client_id']),form=True)
            self.file.unlink(missing_ok=True)
