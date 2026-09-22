"""Verified versioned worker copies, independent of the plugin's disposable cache."""
import hashlib
import json
import os
from pathlib import Path
import re
import secrets
import shutil
import subprocess
import sys
import time

from auth_client import ClientError, VERSION, app_dir, mutex


def file_sha256(path):
    digest = hashlib.sha256()
    with Path(path).open('rb') as stream:
        for block in iter(lambda: stream.read(1024 * 1024), b''):
            digest.update(block)
    return digest.hexdigest()


def _ordinary(path):
    return not path.is_symlink() and not (getattr(path.lstat(), 'st_file_attributes', 0) & 0x400)


def ensure_runtime(root=None, source=None, expected_sha256=None):
    """Copy a frozen executable only after validating the shipped checksum sidecar."""
    source = Path(source or sys.executable).absolute()
    root = Path(root or app_dir()).absolute()
    if not source.is_file() or not _ordinary(source):
        raise ClientError('插件程序不存在或是链接，请重新安装插件。', 'runtime_invalid')
    if expected_sha256 is None:
        try:
            expected_sha256 = source.with_suffix(source.suffix + '.sha256').read_text('ascii').split()[0]
        except (OSError, UnicodeError, IndexError):
            raise ClientError('插件缺少程序校验信息，请重新安装。', 'runtime_invalid') from None
    if not isinstance(expected_sha256, str) or not re.fullmatch('[a-f0-9]{64}', expected_sha256):
        raise ClientError('插件程序校验信息无效。', 'runtime_invalid')
    if file_sha256(source) != expected_sha256:
        raise ClientError('插件程序 SHA-256 校验失败，请重新安装。', 'runtime_invalid')
    with mutex('runtime', root=root):
        root.mkdir(parents=True, exist_ok=True)
        folder = root / 'runtime' / (VERSION + '-' + expected_sha256[:16])
        for part in (root / 'runtime', folder):
            if part.exists() and (not part.is_dir() or not _ordinary(part)):
                raise ClientError('本地运行目录不是普通目录。', 'runtime_invalid')
            part.mkdir(exist_ok=True)
        destination = folder / source.name
        if destination.exists():
            if not destination.is_file() or not _ordinary(destination) or file_sha256(destination) != expected_sha256:
                raise ClientError('本地运行程序校验失败，请重新安装插件。', 'runtime_invalid')
        else:
            temporary = folder / ('.runtime-' + secrets.token_hex(8) + '.tmp')
            try:
                shutil.copyfile(source, temporary)
                if file_sha256(temporary) != expected_sha256:
                    raise ClientError('复制程序时校验失败。', 'runtime_invalid')
                temporary.replace(destination)
            finally:
                temporary.unlink(missing_ok=True)
        sidecar = destination.with_suffix(destination.suffix + '.sha256')
        if sidecar.exists() and not _ordinary(sidecar):
            raise ClientError('本地校验文件不是普通文件。', 'runtime_invalid')
        sidecar.write_text(expected_sha256 + '  ' + destination.name + '\n', encoding='ascii')
        return destination


def spawn_worker(mode, args=(), env=None, root=None):
    """Start an isolated hidden worker; stdout/stderr never enter MCP protocol output."""
    flags = {'login': '--login-worker', 'download': '--worker'}
    if mode not in flags:
        raise ValueError('Unknown worker mode')
    root = Path(root or app_dir()).absolute()
    root.mkdir(parents=True, exist_ok=True)
    if getattr(sys, 'frozen', False):
        command = [str(ensure_runtime(root=root))]
    else:
        command = [sys.executable, str(Path(__file__).with_name('factor_bridge.py').absolute())]
    command += [flags[mode], *map(str, args), '--state-root', str(root)]
    options = dict(stdin=subprocess.DEVNULL, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
                   close_fds=True, cwd=str(root))
    if env is not None or getattr(sys, 'frozen', False):
        options['env'] = {**os.environ, **(env or {})}
    if getattr(sys, 'frozen', False):
        # A detached task must unpack independently of the parent MCP's lifetime.
        options['env']['PYINSTALLER_RESET_ENVIRONMENT'] = '1'
    if os.name == 'nt':
        # Ask Windows for a permitted independent lifetime. DETACHED_PROCESS only
        # detaches the console: it does not escape a host's kill-on-close job.
        # If that job forbids breakaway, fall back only to its normal child
        # lifetime and report the limitation. Never use an external launcher.
        options['creationflags'] = (subprocess.CREATE_NO_WINDOW | subprocess.DETACHED_PROCESS |
                                    subprocess.CREATE_BREAKAWAY_FROM_JOB)
    else:
        options['start_new_session'] = True
    lifetime='independent'
    try:
        process=subprocess.Popen(command, **options)
    except OSError as error:
        if os.name == 'nt' and getattr(error, 'winerror', None) == 5:
            options['creationflags'] &= ~subprocess.CREATE_BREAKAWAY_FROM_JOB
            try:process=subprocess.Popen(command, **options)
            except OSError:
                raise ClientError('无法启动本地后台任务，请检查插件安装和程序运行权限。', 'worker_start_failed') from None
            lifetime='host_bound'
        else:
            raise ClientError('无法启动本地后台任务，请检查插件安装和程序运行权限。', 'worker_start_failed') from None
    process.xyquant_lifetime=lifetime
    temporary=root/('.runtime-status-'+secrets.token_hex(6)+'.tmp')
    try:
        temporary.write_text(json.dumps({'background_lifetime':lifetime,'checked_at':time.time()}),encoding='utf-8')
        temporary.replace(root/'runtime_status.json')
    except OSError:
        pass
    finally:
        temporary.unlink(missing_ok=True)
    return process


def runtime_status(root=None):
    """Last observed worker lifetime, not a promise about another client's policy."""
    try:
        result=json.loads((Path(root or app_dir())/'runtime_status.json').read_text('utf-8'))
        lifetime=result.get('background_lifetime')
    except (OSError,ValueError,TypeError):
        lifetime='unknown'
    if lifetime not in ('independent','host_bound'):lifetime='unknown'
    notice={
        'host_bound':'当前客户端只允许随宿主运行的后台任务。请在登录或下载完成前保持本次 Codex 对话运行；结束对话或关闭 Codex 可能中断尚未完成的操作。插件遵守宿主策略，不绕过限制。',
        'independent':'最近一次后台任务获准独立运行；关闭 Codex 不会直接结束该任务。',
        'unknown':'尚未验证当前客户端是否允许独立后台任务；登录或下载期间请保持 Codex 对话运行。',
    }[lifetime]
    return {'background_lifetime':lifetime,'background_notice':notice}


def process_alive(pid):
    if not isinstance(pid, int) or pid <= 0:
        return False
    if os.name == 'nt':
        import ctypes
        from ctypes import wintypes
        kernel = ctypes.WinDLL('kernel32', use_last_error=True)
        kernel.OpenProcess.argtypes = [wintypes.DWORD, wintypes.BOOL, wintypes.DWORD]
        kernel.OpenProcess.restype = wintypes.HANDLE
        kernel.GetExitCodeProcess.argtypes = [wintypes.HANDLE, ctypes.POINTER(wintypes.DWORD)]
        kernel.CloseHandle.argtypes = [wintypes.HANDLE]
        handle = kernel.OpenProcess(0x1000, False, pid)
        if not handle:
            return ctypes.get_last_error() == 5
        try:
            exit_code = wintypes.DWORD()
            return bool(kernel.GetExitCodeProcess(handle, ctypes.byref(exit_code))) and exit_code.value == 259
        finally:
            kernel.CloseHandle(handle)
    try:
        os.kill(pid, 0)
        return True
    except ProcessLookupError:
        return False
    except PermissionError:
        return True
