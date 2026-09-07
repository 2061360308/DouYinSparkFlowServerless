import unittest
from core.handlers.recipient import profile_uid


class TestRecipientURL(unittest.TestCase):
    def test_only_exact_public_profile_origin(self):
        self.assertEqual(profile_uid('https://www.douyin.com/user/MS4wLjAB?from=chat'), 'MS4wLjAB')
        for href in ['https://www.douyin.com.evil/user/a', 'https://evil/user/a',
                     'https://attacker@www.douyin.com/user/a', 'javascript:alert(1)',
                     'https://www.douyin.com/user/a%2Fb', 'https://www.douyin.com:444/user/a',
                     'https://www.douyin.com/user/a%20b']:
            self.assertIsNone(profile_uid(href), href)
