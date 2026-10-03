"""Plugin STDIO MCP: authenticated cloud tools, login and durable local downloads."""
import argparse
import json
import logging
import sys
from pathlib import Path
from typing import Any
from mcp.server import MCPServer
from mcp.server.mcpserver.exceptions import ToolError
from auth_client import ClientError,VERSION
from remote import remote_call
from downloads import Downloads
from login_tasks import LoginTasks

STATE_ROOT = None

def tool_error(error):
    value={'code':error.code,'error':str(error)}
    for key in ('request_id','trace_id'):
        if hasattr(error,key):value[key]=getattr(error,key)
    return ToolError(json.dumps(value,ensure_ascii=False))

logging.basicConfig(level=logging.WARNING)
mcp=MCPServer('XYQuant Factors',version=VERSION,instructions='通过云端查询当前客户获授权因子。尚未登录时调用 start_login，随后 get_login_status，向客户展示授权链接，密码只在网站输入；不索取密码或 API Key，不要求打开连接助手。仅 login_required 才重新登录，权限不足不反复登录。预览最多50行，不能代替全量统计。下载使用真实项目绝对目录，创建导出后调用 download_export 并轮询 get_download，只有本地 ready 且 SHA-256 校验通过才报告成功。request_id 使用 UUID，重试同一请求时复用。研究资料需research:read授权；使用目录version固定后续查询，保留来源、原表指标和警告，净值分页不能代表全量回测。',log_level='WARNING')

async def call(name,data):
    from auth_client import AuthClient
    try:return await remote_call(name,data,AuthClient(STATE_ROOT))
    except ClientError as error:raise tool_error(error) from None

@mcp.tool(structured_output=True)
def get_connection_status()->dict[str,Any]:
    """查看本机保存的连接状态；实际访问权限每次由服务器重新核验。"""
    try:return LoginTasks(STATE_ROOT).status()
    except ClientError as error:raise tool_error(error) from None

@mcp.tool(structured_output=True)
def start_login()->dict[str,Any]:
    """开始或复用后台网页登录任务，快速返回。随后 get_login_status 获取链接；不在对话输入密码。"""
    try:return LoginTasks(STATE_ROOT).start()
    except ClientError as error:raise tool_error(error) from None

@mcp.tool(structured_output=True)
def get_login_status(login_id:str)->dict[str,Any]:
    """查看登录结果及待点击的授权链接。等待期间每次调用快速返回，约每3秒查询一次。"""
    try:return LoginTasks(STATE_ROOT).get(login_id)
    except ClientError as error:raise tool_error(error) from None

@mcp.tool(structured_output=True)
def disconnect()->dict[str,Any]:
    """用户明确要求断开连接时使用，撤销当前授权；已下载文件和云端导出任务保留。"""
    try:return LoginTasks(STATE_ROOT).disconnect()
    except ClientError as error:raise tool_error(error) from None

@mcp.tool(structured_output=True)
async def list_factors(search:str='',page:int=1,page_size:int=20)->dict[str,Any]:
    """分页搜索当前账号获授权的因子。"""
    return await call('list_factors',dict(search=search,page=page,page_size=page_size))
@mcp.tool(structured_output=True)
async def get_factor_info(factor:str)->dict[str,Any]:
    """查看因子说明与可查询日期。"""
    return await call('get_factor_info',dict(factor=factor))
@mcp.tool(structured_output=True)
async def preview_factor(factor:str,start:str,end:str,codes:list[str]|None=None)->dict[str,Any]:
    """预览最多 50 行数据，日期格式 YYYY-MM-DD。"""
    return await call('preview_factor',dict(factor=factor,start=start,end=end,codes=codes or []))
@mcp.tool(structured_output=True)
async def create_export(factors:list[str],start:str,end:str,request_id:str,codes:list[str]|None=None)->dict[str,Any]:
    """创建云端导出任务；重试时复用 request_id。"""
    return await call('create_export',dict(factors=factors,start=start,end=end,request_id=request_id,codes=codes or []))
@mcp.tool(structured_output=True)
async def get_export(job_id:str|None=None,request_id:str|None=None)->dict[str,Any]:
    """查询自己的导出状态；job_id与原创建request_id二选一。提交结果不明时用原request_id核查，404不证明原提交未执行。"""
    if (job_id is None)==(request_id is None):
        raise tool_error(ClientError('job_id 与 request_id 必须恰好提供一个。','invalid_request'))
    return await call('get_export',{key:value for key,value in dict(job_id=job_id,request_id=request_id).items() if value is not None})
@mcp.tool(structured_output=True)
async def list_exports()->dict[str,Any]:
    """列出当前客户的网页与 MCP 导出任务。"""
    return await call('list_exports',{})

@mcp.tool(structured_output=True, annotations={'readOnlyHint': True, 'destructiveHint': False, 'idempotentHint': True})
async def list_strategies(search:str='',category:str='',page:int=1,page_size:int=20,version:str|None=None)->dict[str,Any]:
    """搜索已发布策略，每页最多50条；返回version、来源和统计口径警告，需要research:read授权。"""
    return await call('list_strategies',dict(search=search,category=category,page=page,page_size=page_size,version=version))

@mcp.tool(structured_output=True, annotations={'readOnlyHint': True, 'destructiveHint': False, 'idempotentHint': True})
async def get_strategy_info(strategy_id:str,version:str|None=None)->dict[str,Any]:
    """读取策略说明、报告标题、费用和样本外说明；使用目录返回的strategy_id和version。"""
    return await call('get_strategy_info',dict(strategy_id=strategy_id,version=version))

@mcp.tool(structured_output=True, annotations={'readOnlyHint': True, 'destructiveHint': False, 'idempotentHint': True})
async def get_strategy_performance(strategy_id:str,version:str|None=None)->dict[str,Any]:
    """读取原表整体、年度和月度表现及其统计期间；不重算指标，不执行回测。"""
    return await call('get_strategy_performance',dict(strategy_id=strategy_id,version=version))

@mcp.tool(structured_output=True, annotations={'readOnlyHint': True, 'destructiveHint': False, 'idempotentHint': True})
async def get_strategy_nav(strategy_id:str,version:str,start:str|None=None,end:str|None=None,offset:int=0,limit:int=50)->dict[str,Any]:
    """按日期读取净值分页，每页最多50行；翻页固定version，返回完整性标记，不能当全量回测。"""
    return await call('get_strategy_nav',dict(strategy_id=strategy_id,version=version,start=start,end=end,offset=offset,limit=limit))

@mcp.tool(structured_output=True, annotations={'readOnlyHint': True, 'destructiveHint': False, 'idempotentHint': True})
async def get_research_team(search:str='',page:int=1,page_size:int=20,version:str|None=None)->dict[str,Any]:
    """分页查看已发布团队介绍及联系方式，最多50人；服务端重新验证客户和research:read授权。"""
    return await call('get_research_team',dict(search=search,page=page,page_size=page_size,version=version))

@mcp.tool(structured_output=True, annotations={'readOnlyHint': True, 'destructiveHint': False, 'idempotentHint': True})
async def search_research(query:str='',kind:str='all',page:int=1,page_size:int=20,version:str|None=None,catalog_version:str|None=None)->dict[str,Any]:
    """统一搜索获授权的因子、已发布策略和团队；kind为all/factor/strategy/team，每页最多50条。翻页固定返回的version和catalog_version，不拼接更新前后结果。"""
    return await call('search_research',dict(query=query,kind=kind,page=page,page_size=page_size,version=version,catalog_version=catalog_version))

@mcp.tool(structured_output=True, annotations={'readOnlyHint': True, 'destructiveHint': False, 'idempotentHint': True})
async def compare_strategies(strategy_ids:list[str],version:str)->dict[str,Any]:
    """并列2至4个唯一策略的原表指标与期间；必须使用同一已发布version，保留来源、null和警告，不排名、不重算。"""
    return await call('compare_strategies',dict(strategy_ids=strategy_ids,version=version))

@mcp.tool(structured_output=True, annotations={'readOnlyHint': True, 'destructiveHint': False, 'idempotentHint': True})
async def get_research_updates(page:int=1,page_size:int=10,publication_cursor:int|None=None)->dict[str,Any]:
    """区分软件版本与已发布数据事件，每页最多20条；后续页固定publication_cursor。发布时间不是净值截止日，不自动更新软件或申请新授权。"""
    return await call('get_research_updates',dict(page=page,page_size=page_size,publication_cursor=publication_cursor))

@mcp.tool(structured_output=True)
def download_export(job_id:str,project_dir:str)->dict[str,Any]:
    """后台等待并下载到真实项目绝对目录下 downloads/factors/任务编号。返回本地下载 id，需调用 get_download 查询。"""
    try:return Downloads(STATE_ROOT).start(job_id,project_dir)
    except ClientError as error:raise tool_error(error) from None
@mcp.tool(structured_output=True)
def get_download(download_id:str)->dict[str,Any]:
    """查询本地下载；ready 才代表文件已保存且 SHA-256 校验通过。"""
    try:return Downloads(STATE_ROOT).get(download_id)
    except ClientError as error:raise tool_error(error) from None

if __name__=='__main__':
    parser=argparse.ArgumentParser(description='XYQuant Factors plugin runtime')
    parser.add_argument('--state-root',type=Path)
    mode=parser.add_mutually_exclusive_group()
    mode.add_argument('--stdio',action='store_true')
    mode.add_argument('--worker',action='store_true')
    mode.add_argument('--login-worker')
    mode.add_argument('--migrate-legacy',action='store_true')
    mode.add_argument('--version',action='store_true')
    args=parser.parse_args()
    if args.state_root and not args.state_root.is_absolute():parser.error('state-root must be absolute')
    STATE_ROOT=args.state_root
    if args.version:print(VERSION)
    elif args.worker:Downloads(STATE_ROOT).run()
    elif args.login_worker:LoginTasks(STATE_ROOT).run(args.login_worker)
    elif args.migrate_legacy:
        from configuration import migrate_legacy
        try:print(json.dumps(migrate_legacy(),ensure_ascii=False))
        except ClientError as error:
            print(json.dumps({'error':str(error),'code':error.code},ensure_ascii=False));sys.exit(1)
    else:mcp.run(transport='stdio')
