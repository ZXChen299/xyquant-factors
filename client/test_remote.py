import contextlib
import asyncio
import json
import threading
from types import SimpleNamespace
import unittest
from unittest.mock import AsyncMock, Mock, patch

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
        self.handler=None
        self.call_delay=0
        self.calls=[]
        owner=self
        class Client:
            def __init__(self,transport):pass
            async def __aenter__(self):return self
            async def __aexit__(self,*args):pass
            async def call_tool(self,tool,arguments):
                owner.calls.append((tool,arguments))
                if owner.call_delay:await asyncio.sleep(owner.call_delay)
                if owner.handler:return await owner.handler(tool,arguments)
                if owner.error:raise owner.error
                return owner.result
        self.patches=contextlib.ExitStack()
        self.patches.enter_context(patch('remote.Client',Client))
        self.patches.enter_context(patch('remote.streamable_http_client',return_value=object()))
        self.patches.enter_context(patch('remote.RETRY_DELAYS',(0,0)))
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

    async def test_read_retries_are_bounded_keep_arguments_trace_and_refresh_current_token(self):
        self.auth.access.side_effect=['first-safe-token','second-safe-token','third-safe-token']
        request=httpx2.Request('POST',RESOURCE)
        async def handler(tool,arguments):
            if len(self.calls)<3:raise httpx2.ConnectError('untrusted private transport text',request=request)
            return self.result
        self.handler=handler
        arguments={'factor':'SYNTHETIC'}
        with patch('remote.record') as log:
            value=await remote.remote_call('get_factor_info',arguments,self.auth)
        self.assertIs(value,self.result.structured_content)
        self.assertEqual(len(self.calls),3)
        self.assertTrue(all(args is arguments for _,args in self.calls))
        self.assertEqual(self.auth.access.call_count,3)
        self.auth.invalidate.assert_not_called()
        self.assertEqual(len({call.args[-1] for call in log.call_args_list}),1)
        transport=remote.streamable_http_client.call_args.kwargs['http_client']
        self.assertEqual(transport.headers['Authorization'],'Bearer third-safe-token')
        self.assertEqual(transport.headers['X-Request-ID'],log.call_args.args[-1])

    async def test_refresh_transport_failure_is_never_replayed_or_invalidated(self):
        self.auth.access.side_effect=ClientError('private refresh response lost','network_error')
        await self.assert_failure('network_error')
        self.auth.access.assert_called_once()
        self.auth.invalidate.assert_not_called()
        self.assertEqual(self.calls,[])

    async def test_refresh_timeout_does_not_replay_or_send_tool_with_unknown_token(self):
        finish=threading.Event()
        def access():
            finish.wait(0.2)
            return 'late-synthetic-access-token'
        self.auth.access.side_effect=access
        try:
            with patch('remote.CALL_BUDGET',0.05),self.assertRaises(ClientError) as raised:
                await asyncio.wait_for(remote.remote_call('create_export',{'request_id':'12345678-1234-4234-8234-123456789abc'},self.auth),0.5)
            self.assertEqual(raised.exception.code,'network_error')
            self.auth.access.assert_called_once()
            self.auth.invalidate.assert_not_called()
            self.assertEqual(self.calls,[])
        finally:finish.set()

    async def test_unexpected_auth_io_error_is_sanitized_without_retry(self):
        self.auth.access.side_effect=OSError('private account path and Authorization secret')
        await self.assert_failure('remote_error')
        self.auth.access.assert_called_once()
        self.assertEqual(self.calls,[])

    async def test_expired_budget_does_not_start_auth_or_extend_deadline(self):
        with self.assertRaises(ClientError) as raised:
            await remote.remote_call('list_exports',{},self.auth,deadline=0)
        self.assertEqual(raised.exception.code,'network_error')
        self.auth.access.assert_not_called()
        self.assertEqual(self.calls,[])

    async def test_inflight_read_timeout_is_bounded_and_never_invalidates_login(self):
        self.call_delay=0.2
        with patch('remote.CALL_BUDGET',0.05),self.assertRaises(ClientError) as raised:
            await asyncio.wait_for(remote.remote_call('list_exports',{},self.auth),0.5)
        self.assertEqual(raised.exception.code,'network_error')
        self.assertEqual(len(self.calls),1)
        self.auth.invalidate.assert_not_called()

    async def test_create_response_lost_recovers_by_one_read_without_resubmitting(self):
        business='12345678-1234-4234-8234-123456789abc'
        job={'id':'a'*32,'status':'queued'}
        async def handler(tool,arguments):
            if tool=='create_export':raise httpx2.ConnectError('secret request body',request=httpx2.Request('POST',RESOURCE))
            self.assertEqual((tool,arguments),('get_export',{'request_id':business}))
            return SimpleNamespace(structured_content=job,content=[],is_error=False)
        self.handler=handler
        with patch('remote.record') as log:
            result=await remote.remote_call('create_export',{'request_id':business},self.auth)
        self.assertIs(result,job)
        self.assertEqual([tool for tool,_ in self.calls],['create_export','get_export'])
        self.assertEqual(len({call.args[-1] for call in log.call_args_list}),1)

    async def test_create_not_found_after_lost_response_is_unknown_not_new_export(self):
        business='12345678-1234-4234-8234-123456789abc'
        async def handler(tool,arguments):
            if tool=='create_export':raise httpx2.ReadTimeout('untrusted secret',request=httpx2.Request('POST',RESOURCE))
            return SimpleNamespace(structured_content={'code':'not_found'},content=[],is_error=True)
        self.handler=handler
        with self.assertRaises(ClientError) as raised:
            await remote.remote_call('create_export',{'request_id':business},self.auth)
        self.assertEqual(raised.exception.code,'export_result_unknown')
        self.assertEqual(raised.exception.request_id,business)
        self.assertNotIn('untrusted',str(raised.exception))
        self.assertEqual([tool for tool,_ in self.calls],['create_export','get_export'])

    async def test_create_timeout_with_no_remaining_budget_preserves_business_id(self):
        self.call_delay=0.2
        business='12345678-1234-4234-8234-123456789abc'
        with patch('remote.CALL_BUDGET',0.05),self.assertRaises(ClientError) as raised:
            await asyncio.wait_for(remote.remote_call('create_export',{'request_id':business},self.auth),0.5)
        self.assertEqual(raised.exception.code,'export_result_unknown')
        self.assertEqual(raised.exception.request_id,business)
        self.assertEqual([tool for tool,_ in self.calls],['create_export'])

    async def test_create_and_reconciliation_auth_denials_remain_denials(self):
        business='12345678-1234-4234-8234-123456789abc'
        for denied_tool in ('create_export','get_export'):
            for code in ('login_required','permission_denied'):
                with self.subTest(denied_tool=denied_tool,code=code):
                    self.calls.clear()
                    async def handler(tool,arguments):
                        if tool==denied_tool:return SimpleNamespace(structured_content={'code':code},content=[],is_error=True)
                        raise httpx2.ConnectError('private',request=httpx2.Request('POST',RESOURCE))
                    self.handler=handler
                    with self.assertRaises(ClientError) as raised:
                        await remote.remote_call('create_export',{'request_id':business},self.auth)
                    self.assertEqual(raised.exception.code,code)
                    self.assertEqual(len(self.calls),1 if denied_tool=='create_export' else 2)

    async def test_create_reconciliation_network_failure_is_one_lookup_only(self):
        self.error=httpx2.ConnectError('private',request=httpx2.Request('POST',RESOURCE))
        with self.assertRaises(ClientError) as raised:
            await remote.remote_call('create_export',{'request_id':'12345678-1234-4234-8234-123456789abc'},self.auth)
        self.assertEqual(raised.exception.code,'export_result_unknown')
        self.assertEqual([tool for tool,_ in self.calls],['create_export','get_export'])

    async def test_invalid_trace_is_replaced_and_never_used_as_header(self):
        await remote.remote_call('list_exports',{},self.auth,trace_id='unsafe\r\nAuthorization: private')
        transport=remote.streamable_http_client.call_args.kwargs['http_client']
        self.assertRegex(transport.headers['X-Request-ID'],r'^[a-f0-9]{32}$')


class SDKTransportTests(unittest.IsolatedAsyncioTestCase):
    def setUp(self):
        self.fast_retries=patch('remote.RETRY_DELAYS',(0,0))
        self.fast_retries.start()
        self.addCleanup(self.fast_retries.stop)

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
