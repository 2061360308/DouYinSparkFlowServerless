import unittest
from unittest.mock import AsyncMock, patch
from core.task.run import run_task
from core.api_client import ApiClientError


class TestExecutionRunner(unittest.IsolatedAsyncioTestCase):
    async def test_handler_false_is_not_success(self):
        client = AsyncMock()
        client.get_scheduled_task.return_value = {'enabled': True, 'event_category': 'noop'}
        handler = AsyncMock(return_value={'ok': False, 'reason': 'failed'})
        with patch('core.task.run.get_client', return_value=client), patch('core.task.run.registry.get', return_value=handler):
            result = await run_task('t1')
        self.assertFalse(result['ok'])
        client.mark_result.assert_awaited_once_with('t1', False)

    async def test_duplicate_does_not_call_handler(self):
        client = AsyncMock()
        client.get_scheduled_task.return_value = {'enabled': True, 'event_category': 'douyin_spark'}
        client.claim_execution.return_value = {'claimed': False}
        handler = AsyncMock()
        with patch('core.task.run.get_client', return_value=client), patch('core.task.run.registry.get', return_value=handler):
            result = await run_task('t1', '2026-09-07T05:00:00Z')
        self.assertTrue(result['skipped'])
        handler.assert_not_awaited()

    async def test_lost_claim_response_never_sends(self):
        client = AsyncMock()
        client.get_scheduled_task.return_value = {'enabled': True, 'event_category': 'douyin_spark'}
        client.claim_execution.side_effect = ApiClientError('lost response')
        handler = AsyncMock()
        with patch('core.task.run.get_client', return_value=client), patch('core.task.run.registry.get', return_value=handler):
            result = await run_task('t1')
        self.assertFalse(result['ok'])
        handler.assert_not_awaited()

    async def test_result_write_failure_never_repeats_handler(self):
        client = AsyncMock()
        client.get_scheduled_task.return_value = {'enabled': True, 'event_category': 'douyin_spark'}
        client.claim_execution.return_value = {'claimed': True, 'run_id': 'r1', 'token': 'secret'}
        client.finish_execution.side_effect = ApiClientError('timeout')
        handler = AsyncMock(return_value={'ok': True, 'status': 'submitted'})
        with patch('core.task.run.get_client', return_value=client), patch('core.task.run.registry.get', return_value=handler):
            result = await run_task('t1')
        self.assertEqual(result['status'], 'uncertain')
        self.assertFalse(result['retryable'])
        handler.assert_awaited_once()
