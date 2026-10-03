"""MCP discovery, validated invocation and safe research failures (synthetic only)."""
import unittest
from unittest.mock import AsyncMock, Mock, patch

import factor_bridge
import remote
from mcp.server.mcpserver.exceptions import ToolError


RESEARCH = {'list_strategies', 'get_strategy_info', 'get_strategy_performance',
            'get_strategy_nav', 'get_research_team'}


class ResearchBridgeTests(unittest.IsolatedAsyncioTestCase):
    async def test_discovery_keeps_existing_tools_and_requires_nav_version(self):
        tools = {tool.name: tool for tool in await factor_bridge.mcp.list_tools()}
        self.assertEqual(len(tools), 20)
        self.assertTrue(RESEARCH <= tools.keys())
        self.assertTrue({'start_login', 'preview_factor', 'download_export', 'disconnect'} <= tools.keys())
        for name in RESEARCH:
            self.assertTrue(tools[name].annotations.read_only_hint)
            self.assertFalse(tools[name].annotations.destructive_hint)
            self.assertTrue(tools[name].annotations.idempotent_hint)
        self.assertIn('version', tools['get_strategy_nav'].input_schema['required'])

    async def test_sdk_invocation_preserves_version_metric_names_nulls_and_pagination(self):
        value = {'version': 'a' * 32, 'source': {'sha256': 'b' * 64},
                 'metrics': {'columns': ['收益风险比'], 'values': [1.37]},
                 'rows': [['2026-01-02', None]], 'next_offset': 50, 'has_more': True,
                 'warnings': [{'code': 'period_difference'}]}
        queries = [
            ('list_strategies', {'search': '测试', 'category': '权益', 'page': 2, 'page_size': 1, 'version': 'a' * 32}),
            ('get_strategy_info', {'strategy_id': 's_' + 'b' * 12, 'version': 'a' * 32}),
            ('get_strategy_performance', {'strategy_id': 's_' + 'b' * 12, 'version': 'a' * 32}),
            ('get_strategy_nav', {'strategy_id': 's_' + 'b' * 12, 'version': 'a' * 32, 'start': '2026-01-02', 'end': '2026-02-01', 'offset': 50, 'limit': 50}),
            ('get_research_team', {'search': '合成研究员', 'page': 1, 'page_size': 20, 'version': 'a' * 32}),
        ]
        with patch('factor_bridge.call', new_callable=AsyncMock, return_value=value) as call:
            for tool, args in queries:
                with self.subTest(tool=tool):
                    result = await factor_bridge.mcp.call_tool(tool, args)
                    self.assertFalse(result.is_error)
                    self.assertEqual(result.structured_content, value)
                    call.assert_awaited_with(tool, args)

    async def test_missing_version_rejected_before_remote_access(self):
        with patch('factor_bridge.call', new_callable=AsyncMock) as call:
            with self.assertRaises(ToolError):
                await factor_bridge.mcp.call_tool('get_strategy_nav', {'strategy_id': 's_' + 'b' * 12})
            call.assert_not_called()

    async def test_research_errors_are_sanitized_without_erasing_factor_login(self):
        auth = Mock()
        for code in ['research_authorization_required', 'version_changed', 'content_unavailable', 'research_storage_unavailable']:
            with self.subTest(code=code):
                safe = remote._code({'code': code, 'error': 'secret-token-must-not-escape'})
                failure = remote._failure(safe, auth, 'secret-token-must-not-escape')
                self.assertNotIn('secret-token', str(failure))
                auth.invalidate.assert_not_called()
                with patch('factor_bridge.remote_call', new_callable=AsyncMock, side_effect=failure):
                    with self.assertRaises(ToolError) as error:
                        await factor_bridge.mcp.call_tool('get_research_team', {})
                    self.assertIn(safe, str(error.exception))
                    self.assertNotIn('secret-token', str(error.exception))


if __name__ == '__main__':
    unittest.main()
