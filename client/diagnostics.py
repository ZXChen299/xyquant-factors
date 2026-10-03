"""Bounded local diagnostics: identifiers and classifications, never request data."""
import json
import math
from pathlib import Path
import re
import secrets

from auth_client import ClientError, mutex

MAX_BYTES = 256 * 1024
TOOLS = frozenset(('list_factors', 'get_factor_info', 'preview_factor', 'create_export',
                   'get_export', 'list_exports', 'list_strategies', 'get_strategy_info',
                   'get_strategy_performance', 'get_strategy_nav', 'get_research_team',
                   'download_export'))
STAGES = frozenset(('auth', 'request', 'retry', 'reconcile', 'complete', 'wait', 'download'))
CODES = frozenset(('ok', 'login_required', 'permission_denied', 'busy', 'network_error',
                   'invalid_request', 'not_found', 'source_unavailable',
                   'research_authorization_required', 'version_changed', 'content_unavailable',
                   'idempotency_conflict', 'cancelled', 'interrupted', 'remote_error',
                   'export_result_unknown', 'wait_timeout', 'export_expired', 'account_changed',
                   'download_interrupted', 'checksum_failed', 'disk_full', 'invalid_response'))


def trace_id(value=None):
    return value if isinstance(value, str) and re.fullmatch('[a-f0-9]{32}', value) else secrets.token_hex(16)


def _ordinary(path):
    return not path.is_symlink() and not (getattr(path.lstat(), 'st_file_attributes', 0) & 0x400)


def record(root, tool, stage, elapsed_ms, code, request_id):
    """Best effort, two files maximum, serialized across the shared user's processes."""
    if not isinstance(root, (str, Path)) or tool not in TOOLS or stage not in STAGES or code not in CODES:
        return
    if not isinstance(request_id, str) or not re.fullmatch('[a-f0-9]{32}', request_id):
        return
    if not isinstance(elapsed_ms, (int, float)) or not math.isfinite(elapsed_ms):
        return
    event = dict(tool=tool, stage=stage, elapsed_ms=round(max(0, min(elapsed_ms, 86400000)), 1),
                 code=code, request_id=request_id)
    payload = (json.dumps(event, separators=(',', ':')) + '\n').encode('ascii')
    try:
        root = Path(root)
        if not root.is_absolute() or not root.is_dir():
            return
        if any(not _ordinary(part) for part in (root, *root.parents)):
            return
        with mutex('diagnostics', timeout=0, root=root):
            folder = root / 'diagnostics'
            if folder.exists() and (not folder.is_dir() or not _ordinary(folder)):
                return
            folder.mkdir(exist_ok=True)
            current, previous = folder / 'requests.jsonl', folder / 'requests.previous.jsonl'
            if any(path.exists() and (not path.is_file() or not _ordinary(path)) for path in (current, previous)):
                return
            if current.exists() and current.stat().st_size + len(payload) > MAX_BYTES:
                current.replace(previous)
            with current.open('ab') as stream:
                stream.write(payload)
    except (ClientError, OSError, ValueError, TypeError):
        # Full disks, read-only profiles and concurrent diagnostics never break data access.
        return
