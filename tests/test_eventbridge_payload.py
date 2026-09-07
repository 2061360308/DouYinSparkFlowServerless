import json
import unittest
from core.task.dispatcher import build_fc_schedule
from aliyunFC.taskrunner.invoke_server import _extract_task_id, _extract_scheduled_for


class TestEventBridgePayload(unittest.TestCase):
    def test_event_time_is_preserved_and_missing_time_rejected(self):
        self.assertEqual(_extract_scheduled_for('{"time":"2026-09-07T05:00:00Z"}'), '2026-09-07T05:00:00Z')
        with self.assertRaises(ValueError):
            _extract_scheduled_for('{"task_id":"old-retry"}')
    def test_weekdays_keep_eventbridge_standard_numbering(self):
        schedule = build_fc_schedule({'task_id': 't1', 'cron_expr': '30 9 * * 1-5'}, bus_name='installed-bus', time_zone='GMT+8:00')
        self.assertEqual(schedule['schedule'], '0 30 9 * * 1-5')
        self.assertEqual(schedule['event_bus_name'], 'installed-bus')

    def test_invoke_accepts_direct_data_and_user_data_envelopes(self):
        data = {'task_id': 'test-task'}
        for event in [data, {'data': data}, {'data': json.dumps(data)},
                      {'data': {'UserData': json.dumps(data)}}, {'data': {'UserData': data}}]:
            self.assertEqual(_extract_task_id(json.dumps(event)), 'test-task')

    def test_invalid_payload_does_not_trigger_a_task(self):
        for raw in ['invalid', '[]', '{}', '{"data":{"UserData":"bad-json"}}']:
            self.assertIsNone(_extract_task_id(raw))
