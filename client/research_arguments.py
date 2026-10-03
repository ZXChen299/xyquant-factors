"""Validate new read-tool inputs before the MCP SDK performs coercion.

The SDK accepts extra fields and pre-parses JSON strings by default. Only the
three exploration tools use this guard; existing tool compatibility is retained.
"""
import json
import re

from mcp.server import MCPServer
from mcp.server.mcpserver.exceptions import ToolError


FIELDS = {
    'search_research': {'query', 'kind', 'page', 'page_size', 'version', 'catalog_version'},
    'compare_strategies': {'strategy_ids', 'version'},
    'get_research_updates': {'page', 'page_size', 'publication_cursor'},
}


def _reject():
    raise ToolError(json.dumps({'code': 'invalid_request', 'error': '查询参数类型、范围或字段无效。'}, ensure_ascii=False))


def _integer(data, key, maximum, minimum=1):
    if key in data and (type(data[key]) is not int or not minimum <= data[key] <= maximum):
        _reject()


def _version(value, length):
    if value is not None and (not isinstance(value, str) or not re.fullmatch('[a-f0-9]{' + str(length) + '}', value)):
        _reject()


def validate_explore_arguments(name, arguments):
    if name not in FIELDS:
        return
    if not isinstance(arguments, dict) or set(arguments) - FIELDS[name]:
        _reject()
    if name == 'search_research':
        query, kind = arguments.get('query', ''), arguments.get('kind', 'all')
        if not isinstance(query, str) or len(query) > 200 or not isinstance(kind, str) or kind not in ('all', 'factor', 'strategy', 'team'):
            _reject()
        _integer(arguments, 'page', 1000000)
        _integer(arguments, 'page_size', 50)
        _version(arguments.get('version'), 32)
        _version(arguments.get('catalog_version'), 64)
    elif name == 'compare_strategies':
        ids = arguments.get('strategy_ids')
        if not isinstance(ids, list) or not 2 <= len(ids) <= 4 or any(
                not isinstance(value, str) or not re.fullmatch('s_[a-f0-9]{12}', value) for value in ids):
            _reject()
        if len(set(ids)) != len(ids) or arguments.get('version') is None:
            _reject()
        _version(arguments['version'], 32)
    else:
        _integer(arguments, 'page', 1000000)
        _integer(arguments, 'page_size', 20)
        if arguments.get('publication_cursor') is not None:
            _integer(arguments, 'publication_cursor', 9223372036854775807, minimum=0)


class ExploreMCPServer(MCPServer):
    async def list_tools(self):
        tools = await super().list_tools()
        return [tool.model_copy(update={'input_schema': {**tool.input_schema, 'additionalProperties': False}})
                if tool.name in FIELDS else tool for tool in tools]

    async def call_tool(self, name, arguments, context=None):
        # MCPServer._handle_call_tool delegates here before ToolManager invokes
        # the SDK's coercing validate_arguments/pre_parse_json implementation.
        validate_explore_arguments(name, arguments)
        return await super().call_tool(name, arguments, context)
