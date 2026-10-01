"""Forward MCP calls without exposing transport exceptions or credentials."""
import json
import httpx2
from mcp.client import Client
from mcp.client.streamable_http import streamable_http_client
from mcp.shared.exceptions import MCPError
from auth_client import AuthClient, ClientError, RESOURCE


# Transport errors can contain headers. Use local messages and recognized codes.
MESSAGES = {
    'login_required': '登录授权已失效，请在对话中重新发起登录。',
    'permission_denied': '当前账号无权执行此请求，请检查因子、日期和客户授权。',
    'busy': '服务器繁忙，请稍后重试；创建导出时请复用原请求编号。',
    'network_error': '无法连接因子服务，请检查网络后重试。',
    'invalid_request': '查询条件无效，请检查因子、日期、股票代码及请求参数。',
    'not_found': '因子或任务不存在，或不属于当前账号。',
    'source_unavailable': '源文件暂不可用或已更新，请稍后重试。',
    'research_authorization_required': '当前连接没有研究资料授权。请在网站明确同意 research:read 后重试；已有因子授权继续有效。',
    'version_changed': '研究资料已更新，请重新查询目录并使用新版本重新开始，不能拼接不同版本的数据。',
    'content_unavailable': '研究中心尚未发布资料。',
    'idempotency_conflict': '同一请求编号已用于不同条件，请为新查询使用新的编号。',
    'cancelled': '导出任务已取消，请检查当前授权及任务状态。',
    'interrupted': '服务器重启中断了导出，请使用新的请求编号重新创建任务。',
    'remote_error': '因子服务未能完成请求，请稍后重试。',
}
ALIASES = {
    'authentication_required': 'login_required', 'invalid_token': 'login_required',
    'invalid_key': 'login_required', 'invalid_grant': 'login_required',
    'customer_inactive': 'permission_denied', 'admin_required': 'permission_denied',
    'insufficient_scope': 'permission_denied', 'source_error': 'source_unavailable',
    'research_storage_unavailable': 'source_unavailable',
}


class _ObservedHTTPClient(httpx2.AsyncClient):
    """Retain only a safe error code when the SDK discards HTTP error details."""
    failure = None

    async def send(self, request, *args, **kwargs):
        try:
            response = await super().send(request, *args, **kwargs)
        except (httpx2.RequestError, TimeoutError, ConnectionError):
            self.failure = 'network_error'
            # The SDK logs transport exceptions. Do not let their original text
            # (which can include proxy details or request headers) reach logs.
            raise httpx2.RequestError('Network connection failed.', request=request) from None
        # Unsupported discovery/GET routes are normal SDK fallback, not failures.
        if request.method == 'POST' and response.status_code >= 400:
            self.failure = _code(status=response.status_code)
        return response


def _payload(text):
    """Decode a gateway JSON ToolError, possibly prefixed by the MCP SDK."""
    if not isinstance(text, str) or len(text) > 65536:
        return None
    try:
        value, _ = json.JSONDecoder().raw_decode(text[text.index('{'):])
        return value if isinstance(value, dict) else None
    except (ValueError, TypeError):
        return None


def _code(payload=None, status=None):
    if status == 401:
        return 'login_required'
    if status == 403:
        return 'permission_denied'
    if status in (429, 503):
        return 'busy'
    if status == 404:
        return 'not_found'
    if status == 400:
        return 'invalid_request'
    if isinstance(payload, dict):
        value = payload.get('code')
        if not isinstance(value, str):
            value = payload.get('error')
        if isinstance(value, str):
            value = ALIASES.get(value, value)
            if value in MESSAGES:
                return value
        if payload.get('retryable') is True:
            return 'busy'
    return 'remote_error'


def _exception_code(error):
    """The SDK may wrap HTTPStatusError in ExceptionGroup during cleanup."""
    pending = [error]
    seen = set()
    network = False
    while pending and len(seen) < 32:
        current = pending.pop(0)
        if id(current) in seen:
            continue
        seen.add(id(current))
        if isinstance(current, httpx2.HTTPStatusError):
            return _code(status=current.response.status_code)
        if isinstance(current, (httpx2.RequestError, TimeoutError, ConnectionError)):
            network = True
        if isinstance(current, MCPError):
            payload = current.data if isinstance(current.data, dict) else _payload(current.message)
            code = _code(payload)
            if code != 'remote_error':
                return code
        pending.extend(e for e in getattr(current, 'exceptions', ()) if isinstance(e, BaseException))
        pending.extend(e for e in (current.__cause__, current.__context__) if e is not None)
    return 'network_error' if network else 'remote_error'


def _failure(code, auth, token):
    if code == 'login_required':
        # Must not erase a concurrent refreshed login when an older request fails.
        auth.invalidate(token)
    return ClientError(MESSAGES[code], code)


async def remote_call(tool, arguments, auth=None):
    """Keep tool arguments/results unchanged; authentication is entirely local."""
    auth = auth or AuthClient()
    token = auth.access()
    http = None
    try:
        async with _ObservedHTTPClient(
            headers={'Authorization': 'Bearer ' + token}, timeout=50, trust_env=False
        ) as http:
            async with Client(streamable_http_client(RESOURCE, http_client=http)) as client:
                result = await client.call_tool(tool, arguments)
    except ClientError:
        raise
    except Exception as error:
        code = http.failure if http is not None and http.failure else _exception_code(error)
        raise _failure(code, auth, token) from None

    content = result.structured_content
    if content is None:
        content = _payload(''.join(getattr(block, 'text', '') for block in result.content))
    if result.is_error:
        raise _failure(_code(content), auth, token) from None
    if content is None:
        raise ClientError('因子服务返回了无法识别的数据，请稍后重试。', 'remote_error')
    return content
