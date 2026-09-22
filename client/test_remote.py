import contextlib
import asyncio
import json
from types import SimpleNamespace
import unittest
from unittest.mock import Mock, patch

import httpx2
from mcp.shared.exceptions import MCPError

from auth_client import ClientError, RESOURCE
import remote


class RemoteTests(unittest.IsolatedAsyncioTestCase):
    def setUp(self):
        self.auth=Mock()
        self.auth.access.return_value='test-credential-never-display'
        self.result=SimpleNamespace(structured_content={'ok':True},content=[],is_error=False)
        self.error=None
        self.calls=[]
        owner=self
        class Client:
            def __init__(self,transport):pass
            async def __aenter__(self):return self
            async def __aexit__(self,*args):pass
            async def call_tool(self,tool,arguments):
                owner.calls.append((tool,arguments))
                if owner.error:raise owner.error
                return owner.result
        self.patches=contextlib.ExitStack()
        self.patches.enter_context(patch('remote.Client',Client))
        self.patches.enter_context(patch('remote.streamable_http_client',return_value=object()))
        self.addCleanup(self.patches.close)

    async def assert_failure(self,expected):
        with self.assertRaises(ClientError) as raised:
            await remote.remote_call('get_factor_info',{'factor':'vol_entropy'},self.auth)
        self.assertEqual(raised.exception.code,expected)
        self.assertNotIn('test-credential',str(raised.exception))
        self.assertNotIn('Authorization',str(raised.exception))
        return raised.exception

    async def test_six_tools_preserve_arguments_and_structured_results(self):
        rows=[{'date':'2026-09-11','code':'000001.SZ','value':None}]
        self.result.structured_content={'rows':rows,'bytes':192,'sha256':'a'*64}
        arguments={'factor':'vol_entropy','start':'2026-09-11','end':'2026-09-11','codes':['000001.SZ']}
        for tool in ('list_factors','get_factor_info','preview_factor','create_export','get_export','list_exports'):
            with self.subTest(tool=tool):
                result=await remote.remote_call(tool,arguments,self.auth)
                self.assertIs(result,self.result.structured_content)
                self.assertEqual(self.calls[-1],(tool,arguments))
                self.assertIs(self.calls[-1][1],arguments)
        self.auth.invalidate.assert_not_called()

    async def test_http_auth_permissions_busy_and_network_are_distinct(self):
        request=httpx2.Request('POST',RESOURCE,headers={'Authorization':'Bearer test-credential-never-display'})
        for status,code in ((401,'login_required'),(403,'permission_denied'),(429,'busy'),(503,'busy'),(400,'invalid_request'),(404,'not_found')):
            with self.subTest(status=status):
                self.auth.invalidate.reset_mock()
                http_error=httpx2.HTTPStatusError('Authorization: test-credential-never-display',request=request,response=httpx2.Response(status,request=request))
                self.error=ExceptionGroup('SDK transport failure',[ExceptionGroup('nested',[http_error])])
                await self.assert_failure(code)
                if status==401:self.auth.invalidate.assert_called_once_with(self.auth.access.return_value)
                else:self.auth.invalidate.assert_not_called()
        self.error=httpx2.ConnectError('Authorization: test-credential-never-display',request=request)
        await self.assert_failure('network_error')

    async def test_tool_error_codes_and_malformed_error_never_echo_text(self):
        self.result.is_error=True
        for source,target in (('invalid_token','login_required'),('customer_inactive','permission_denied'),('permission_denied','permission_denied'),('busy','busy'),('source_error','source_unavailable'),('idempotency_conflict','idempotency_conflict')):
            with self.subTest(source=source):
                self.result.structured_content=None
                value={'code':source,'error':'Authorization: test-credential-never-display'}
                self.result.content=[SimpleNamespace(text='Error calling tool: '+json.dumps(value))]
                await self.assert_failure(target)
        self.result.content=[SimpleNamespace(text='Authorization: test-credential-never-display')]
        await self.assert_failure('remote_error')

    async def test_mcp_exception_data_and_unknown_exception_are_sanitized(self):
        self.error=MCPError(-32603,'Authorization: test-credential-never-display',{'code':'permission_denied'})
        await self.assert_failure('permission_denied')
        self.error=RuntimeError('Authorization: test-credential-never-display')
        await self.assert_failure('remote_error')

    async def test_json_fallback_and_bad_success_response(self):
        self.result.structured_content=None
        self.result.content=[SimpleNamespace(text='{"rows": [{"value": null}]}')]
        self.assertEqual(await remote.remote_call('preview_factor',{},self.auth),{'rows':[{'value':None}]})
        self.result.content=[SimpleNamespace(text='unexpected Authorization: test-credential-never-display')]
        await self.assert_failure('remote_error')


class SDKTransportTests(unittest.IsolatedAsyncioTestCase):
    async def test_real_sdk_keeps_http_classification_when_sdk_synthesizes_mcp_error(self):
        client_class=remote._ObservedHTTPClient
        auth=Mock()
        auth.access.return_value='test-only-secret'
        for status,code in ((401,'login_required'),(403,'permission_denied'),(429,'busy'),(503,'busy')):
            with self.subTest(status=status):
                def handler(request):return httpx2.Response(status,json={'error':'fixture rejected'},request=request)
                def factory(*args,**kwargs):return client_class(*args,**kwargs,transport=httpx2.MockTransport(handler))
                with patch('remote._ObservedHTTPClient',factory),self.assertRaises(ClientError) as raised:
                    await asyncio.wait_for(remote.remote_call('list_factors',{},auth),timeout=5)
                self.assertEqual(raised.exception.code,code)
                self.assertNotIn('test-only-secret',str(raised.exception))

    async def test_real_sdk_network_failure_does_not_request_login(self):
        client_class=remote._ObservedHTTPClient
        auth=Mock()
        auth.access.return_value='test-only-secret'
        def handler(request):raise httpx2.ConnectError('test-only-secret',request=request)
        def factory(*args,**kwargs):return client_class(*args,**kwargs,transport=httpx2.MockTransport(handler))
        with patch('remote._ObservedHTTPClient',factory),patch('logging.Logger.exception'),self.assertRaises(ClientError) as raised:
            await asyncio.wait_for(remote.remote_call('list_factors',{},auth),timeout=5)
        self.assertEqual(raised.exception.code,'network_error')
        auth.invalidate.assert_not_called()

    async def test_network_exception_handed_to_sdk_is_sanitized(self):
        def handler(request):raise httpx2.ConnectError('Authorization: test-only-secret',request=request)
        async with remote._ObservedHTTPClient(transport=httpx2.MockTransport(handler)) as client:
            with self.assertRaises(httpx2.RequestError) as raised:await client.post(RESOURCE)
        self.assertNotIn('test-only-secret',str(raised.exception))
        self.assertTrue(raised.exception.__suppress_context__)


if __name__=='__main__':unittest.main()
