"""Synthetic contracts for search, comparison and publication history. No login."""
import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import AsyncMock, Mock, patch

import auth_client
import diagnostics
import factor_bridge
import remote
from mcp.server.mcpserver.exceptions import ToolError


EXPLORE = {'search_research', 'compare_strategies', 'get_research_updates'}


class ExploreBridgeTests(unittest.IsolatedAsyncioTestCase):
    async def test_discovery_requires_comparison_version_and_keeps_existing_scopes(self):
        tools = {tool.name: tool for tool in await factor_bridge.mcp.list_tools()}
        self.assertEqual(len(tools), 20)
        self.assertTrue(EXPLORE <= tools.keys())
        for name in EXPLORE:
            self.assertTrue(tools[name].annotations.read_only_hint)
            self.assertTrue(tools[name].annotations.idempotent_hint)
            self.assertFalse(tools[name].annotations.destructive_hint)
        self.assertEqual(set(tools['compare_strategies'].input_schema['required']), {'strategy_ids', 'version'})
        self.assertIn('catalog_version', tools['search_research'].input_schema['properties'])
        self.assertIn('publication_cursor', tools['get_research_updates'].input_schema['properties'])
        self.assertEqual(auth_client.SCOPES, 'factors:read factors:export factors:download research:read')

    async def test_search_pagination_retains_explicit_null_research_version(self):
        args = dict(query='synthetic', kind='all', page=2, page_size=1, version=None, catalog_version='c' * 64)
        value = dict(version=None, catalog_version='c' * 64, available_kinds=['factor'],
                     items=[dict(kind='factor', id='synthetic', coverage=None)], counts={'factor': 2},
                     total=2, page=2, page_size=1, has_more=False, warnings=['research_not_published'])
        with patch('factor_bridge.call', new_callable=AsyncMock, return_value=value) as call:
            result = await factor_bridge.mcp.call_tool('search_research', args)
        self.assertFalse(result.is_error)
        self.assertEqual(result.structured_content, value)
        call.assert_awaited_once_with('search_research', args)

    async def test_comparison_preserves_requested_order_raw_metrics_nulls_and_period_warning(self):
        ids = ['s_' + 'b' * 12, 's_' + 'a' * 12]
        args = dict(strategy_ids=ids, version='c' * 32)
        value = dict(version='c' * 32, source={'sha256': 'd' * 64}, periods_match=False,
                     strategies=[dict(id=ids[0], metrics={'收益风险比': None}, nav_range=None),
                                 dict(id=ids[1], metrics={'收益风险比': '原始文本'}, nav_range={'end': '2026-01-02'})],
                     warnings=['periods_differ'], basis='original table, no new backtest')
        with patch('factor_bridge.call', new_callable=AsyncMock, return_value=value) as call:
            result = await factor_bridge.mcp.call_tool('compare_strategies', args)
        self.assertEqual(result.structured_content, value)
        call.assert_awaited_once_with('compare_strategies', args)

    async def test_missing_comparison_version_is_rejected_before_remote_access(self):
        with patch('factor_bridge.call', new_callable=AsyncMock) as call:
            with self.assertRaises(ToolError):
                await factor_bridge.mcp.call_tool('compare_strategies', {'strategy_ids': ['s_' + 'a' * 12, 's_' + 'b' * 12]})
            call.assert_not_called()

    async def test_updates_preserve_zero_and_fixed_cursor_and_separate_software_from_data(self):
        for cursor in (None, 0, 41):
            with self.subTest(cursor=cursor):
                args = dict(page=2, page_size=1, publication_cursor=cursor)
                value = dict(software={'version': 'synthetic-candidate', 'changes': []}, data=[],
                             publication_cursor=cursor, page=2, page_size=1, has_more=False,
                             total=0, warnings=['research_scope_missing'])
                with patch('factor_bridge.call', new_callable=AsyncMock, return_value=value) as call:
                    result = await factor_bridge.mcp.call_tool('get_research_updates', args)
                self.assertEqual(result.structured_content, value)
                call.assert_awaited_once_with('get_research_updates', args)

    async def test_new_read_tools_retry_safely_without_changing_versions_cursors_or_trace(self):
        for tool in sorted(EXPLORE):
            with self.subTest(tool=tool):
                auth = Mock()
                args = {'version': 'a' * 32, 'catalog_version': 'b' * 64, 'publication_cursor': 0}
                value = {'synthetic': None}
                with patch('remote.auth_access', new_callable=AsyncMock, return_value='synthetic-token'), \
                     patch('remote._attempt', new_callable=AsyncMock,
                           side_effect=[remote._AttemptFailure('network_error'), value]) as attempt, \
                     patch('remote.RETRY_DELAYS', (0, 0)), patch('remote.record') as log:
                    self.assertIs(await remote.remote_call(tool, args, auth), value)
                self.assertEqual(attempt.await_count, 2)
                self.assertTrue(all(call.args[0] == tool and call.args[1] is args for call in attempt.await_args_list))
                self.assertEqual(len({call.args[3] for call in attempt.await_args_list}), 1)
                self.assertEqual(len({call.args[-1] for call in log.call_args_list}), 1)
                auth.invalidate.assert_not_called()

    async def test_denials_and_changed_versions_stop_immediately_and_preserve_connection(self):
        for code in ('permission_denied', 'research_authorization_required', 'version_changed', 'invalid_request'):
            for tool in sorted(EXPLORE):
                with self.subTest(code=code, tool=tool):
                    auth = Mock()
                    with patch('remote.auth_access', new_callable=AsyncMock, return_value='synthetic-secret'), \
                         patch('remote._attempt', new_callable=AsyncMock, side_effect=remote._AttemptFailure(code)) as attempt, \
                         patch('remote.record'), self.assertRaises(auth_client.ClientError) as error:
                        await remote.remote_call(tool, {}, auth)
                    self.assertEqual(error.exception.code, code)
                    self.assertNotIn('synthetic-secret', str(error.exception))
                    attempt.assert_awaited_once()
                    auth.invalidate.assert_not_called()

    async def test_diagnostics_admit_new_tool_names_without_query_or_response_content(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            for tool in sorted(EXPLORE):
                diagnostics.record(root, tool, 'complete', 1, 'ok', 'a' * 32)
            rows = [json.loads(line) for line in (root / 'diagnostics/requests.jsonl').read_text().splitlines()]
        self.assertEqual({row['tool'] for row in rows}, EXPLORE)
        self.assertTrue(all(set(row) == {'tool', 'stage', 'elapsed_ms', 'code', 'request_id'} for row in rows))


if __name__ == '__main__':
    unittest.main()
