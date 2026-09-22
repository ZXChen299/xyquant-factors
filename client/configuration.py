"""Surgical, backed-up Codex configuration changes."""
import os
import hashlib
from pathlib import Path
import secrets
import shutil
import time
import tomlkit
from auth_client import ORIGIN,ClientError,app_dir,mutex

SERVER='xyquant_factors'


def config_path():return Path(os.environ.get('CODEX_HOME',str(Path.home()/'.codex')))/'config.toml'


def owned(entry,bridge):
    if not hasattr(entry,'get'):return False
    if entry.get('url') is not None:return entry.get('url')==ORIGIN+'/mcp' and not entry.get('command')
    try:return bool(entry.get('command')) and Path(entry['command']).is_absolute() and Path(entry['command']).resolve()==Path(bridge).resolve() and entry.get('args')==['--stdio']
    except (OSError,ValueError):return False


def _replace_config(path,original,output):
    """Back up exact bytes and atomically replace only a still-current config."""
    tomlkit.parse(output)
    path.parent.mkdir(parents=True,exist_ok=True)
    expected=original.encode('utf-8')
    if (path.read_bytes() if path.exists() else b'')!=expected:
        raise ClientError('Codex 配置刚被其他程序修改，请重试；配置未覆盖。','config_changed')
    backup=None
    if path.exists():
        backup=path.with_name('config.before-xyquant-'+str(time.time_ns())+'.toml.bak')
        with backup.open('xb') as target:target.write(expected)
        shutil.copystat(path,backup)
    temp=path.with_name(path.name+'.'+secrets.token_hex(6)+'.tmp')
    try:
        with temp.open('x',encoding='utf-8',newline='') as target:
            target.write(output);target.flush();os.fsync(target.fileno())
        if (path.read_bytes() if path.exists() else b'')!=expected:
            raise ClientError('Codex 配置刚被其他程序修改，请重试；配置未覆盖。','config_changed')
        temp.replace(path)
    finally:temp.unlink(missing_ok=True)
    return backup


def migrate_legacy(path=None):
    """Remove only our old standalone MCP entry; preserve credentials and jobs."""
    path=Path(path) if path else config_path()
    with mutex('configuration'):
        original=path.read_bytes().decode('utf-8') if path.exists() else ''
        try:doc=tomlkit.parse(original)
        except Exception:raise ClientError('Codex 配置文件格式有误，请先修复；原文件未修改。','config_invalid') from None
        servers=doc.get('mcp_servers',{})
        if not hasattr(servers,'get'):
            raise ClientError('Codex MCP 配置格式有误；原文件未修改。','config_invalid')
        entry=servers.get(SERVER)
        if entry is None:
            return {'changed':False,'config_path':str(path),'backup_path':None,'restart_required':False}
        if not owned(entry,app_dir()/'FactorBridge.exe'):
            raise ClientError('xyquant_factors 的旧配置无法确认为本服务，已停止迁移；请保留原配置并检查服务归属。','config_conflict')
        del doc['mcp_servers'][SERVER]
        backup=_replace_config(path,original,tomlkit.dumps(doc))
        return {'changed':True,'config_path':str(path),'backup_path':str(backup),'restart_required':True}


def configure(bridge,path=None,remove=False):
    path=Path(path) if path else config_path();bridge=Path(bridge).resolve()
    with mutex('configuration'):
        original=path.read_bytes().decode('utf-8') if path.exists() else ''
        try:doc=tomlkit.parse(original)
        except Exception:raise ClientError('Codex 配置文件格式有误，请先修复；原文件未修改。') from None
        servers=doc.get('mcp_servers',{});entry=servers.get(SERVER)
        if entry is not None and not owned(entry,bridge):raise ClientError('xyquant_factors 已用于其他配置，已停止覆盖。请先在 Codex 中为原服务改名。','config_conflict')
        if remove:
            if entry is None:return
            del doc['mcp_servers'][SERVER]
        else:
            if 'mcp_servers' not in doc:doc['mcp_servers']=tomlkit.table()
            updated=tomlkit.table();updated['command']=str(bridge);updated['args']=['--stdio'];updated['startup_timeout_sec']=30;updated['tool_timeout_sec']=60
            doc['mcp_servers'][SERVER]=updated
        output=tomlkit.dumps(doc);tomlkit.parse(output)
        if output==original:return
        _replace_config(path,original,output)


def install_files(gui_exe,bridge_exe):
    destination=app_dir();destination.mkdir(parents=True,exist_ok=True)
    for source,name in [(Path(gui_exe),'FactorConnect.exe'),(Path(bridge_exe),'FactorBridge.exe')]:
        target=destination/name
        if source.resolve()==target.resolve():continue
        if target.is_file() and source.stat().st_size==target.stat().st_size:
            if hashlib.sha256(source.read_bytes()).digest()==hashlib.sha256(target.read_bytes()).digest():continue
        temp=destination/(name+'.new')
        try:shutil.copy2(source,temp);temp.replace(target)
        except PermissionError:raise ClientError('助手正在运行，请关闭其他助手和 Codex 后重新安装。') from None
        finally:temp.unlink(missing_ok=True)
    return destination/'FactorBridge.exe'
