import unittest
from core.services.task_scheduling import sync_error, MissingScheduleConfig
from core.task.dispatcher import EventSourceError


class TestScheduleErrors(unittest.TestCase):
    def test_actionable_safe_categories(self):
        for error, expected in [
            (MissingScheduleConfig(), '配置缺失'),
            (EventSourceError('AccessDenied'), '权限不足'),
            (EventSourceError('SignatureDoesNotMatch'), '身份验证失败'),
            (EventSourceError('Throttling'), '限流'),
            (TimeoutError('secret-in-message'), '尚未确认'),
            (FileNotFoundError('secret-in-path'), '本机调度程序'),
        ]:
            self.assertIn(expected, sync_error(error))
            self.assertNotIn('secret', sync_error(error))
        self.assertNotIn('sensitive', sync_error(EventSourceError('sensitive-untrusted-code')))
