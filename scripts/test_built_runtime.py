"""Post-build offline smoke check of the actual EXE, with isolated local state."""
import asyncio
import json
from pathlib import Path
import subprocess
import sys
import tempfile

from mcp import ClientSession, StdioServerParameters
from mcp.client.stdio import stdio_client

ROOT=Path(__file__).resolve().parents[1]
EXPECTED={'get_connection_status','start_login','get_login_status','disconnect','list_factors','get_factor_info',
          'preview_factor','create_export','get_export','list_exports','list_strategies','get_strategy_info',
          'get_strategy_performance','get_strategy_nav','get_research_team','download_export','get_download',
          'search_research','compare_strategies','get_research_updates'}


async def check(binary,root,version):
    parameters=StdioServerParameters(command=str(binary),args=['--stdio','--state-root',str(root)])
    async with stdio_client(parameters) as (reader,writer):
        async with ClientSession(reader,writer) as session:
            initialized=await session.initialize()
            if initialized.server_info.version!=version:raise ValueError('Bundled runtime version mismatch.')
            tools=await session.list_tools()
            if {tool.name for tool in tools.tools}!=EXPECTED:raise ValueError('Bundled runtime tool set mismatch.')
            return dict(version=version,tools=len(tools.tools),protocol=initialized.protocol_version,network_tools_called=0)


def main():
    binary=ROOT/'plugins/xyquant-factors/bin/FactorBridge.exe'
    metadata=json.loads((ROOT/'plugins/xyquant-factors/release.json').read_text(encoding='utf8'))
    actual=subprocess.check_output([str(binary),'--version'],timeout=30).decode().strip()
    if actual!=metadata['version']:raise ValueError('Bundled CLI version mismatch.')
    with tempfile.TemporaryDirectory(prefix='xyquant-offline-smoke-') as td:
        result=asyncio.run(asyncio.wait_for(check(binary,Path(td),metadata['version']),timeout=30))
    print(json.dumps(result))


if __name__=='__main__':main()
