"""Local MCP protocol coverage for unambiguous export recovery."""
import unittest
from unittest.mock import AsyncMock, patch

from auth_client import ClientError
import factor_bridge
from mcp.server.mcpserver.exceptions import ToolError


class ExportRecoveryBridgeTests(unittest.IsolatedAsyncioTestCase):
    async def test_existing_job_and_business_request_lookup_keep_twenty_tools(self):
        tools={tool.name:tool for tool in await factor_bridge.mcp.list_tools()}
        self.assertEqual(len(tools),20)
        self.assertIn('request_id',tools['get_export'].input_schema['properties'])
        for args in ({'job_id':'a'*32},{'request_id':'12345678-1234-4234-8234-123456789abc'}):
            with patch('factor_bridge.call',new_callable=AsyncMock,return_value={'status':'queued'}) as call:
                result=await factor_bridge.mcp.call_tool('get_export',args)
                self.assertFalse(result.is_error)
                call.assert_awaited_once_with('get_export',args)

    async def test_missing_or_ambiguous_lookup_rejected_before_remote_call(self):
        for args in ({},{'job_id':'a'*32,'request_id':'12345678-1234-4234-8234-123456789abc'}):
            with patch('factor_bridge.call',new_callable=AsyncMock) as call,self.assertRaises(ToolError) as raised:
                await factor_bridge.mcp.call_tool('get_export',args)
            self.assertIn('invalid_request',str(raised.exception))
            call.assert_not_called()

    async def test_unknown_export_preserves_business_and_trace_ids_in_tool_error(self):
        error=ClientError('Keep original request id','export_result_unknown')
        error.request_id='12345678-1234-4234-8234-123456789abc'
        error.trace_id='b'*32
        with patch('factor_bridge.remote_call',new_callable=AsyncMock,side_effect=error),self.assertRaises(ToolError) as raised:
            await factor_bridge.mcp.call_tool('create_export',{'factors':['synthetic'],
                'start':'2026-01-01','end':'2026-01-01','request_id':error.request_id})
        self.assertIn(error.request_id,str(raised.exception))
        self.assertIn(error.trace_id,str(raised.exception))


if __name__=='__main__':unittest.main()
