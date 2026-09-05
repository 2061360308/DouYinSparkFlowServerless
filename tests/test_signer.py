"""browser.signer 单元测试：与 FC 签名参考实现逐字节比对（HMAC-SHA256）。

参考实现按阿里云各 FC SDK 通用签名算法独立重写，用于校验本仓 signer 的正确性。
纯同步、无 DB / 网络依赖。
"""

import base64
import hashlib
import hmac
import unittest

from browser import signer


def _ref_sign(secret, method, path, headers, queries=None):
    """独立参考实现：Base64(HMAC-SHA256(SK, StringToSign))。"""
    def h(name):
        for k, v in headers.items():
            if k.lower() == name:
                return "" if v is None else str(v)
        return ""

    ss = f"{method.upper()}\n{h('content-md5')}\n{h('content-type')}\n{h('date')}\n"
    fc = {k.lower(): ("" if v is None else str(v))
          for k, v in headers.items() if k.lower().startswith("x-fc-")}
    for k in sorted(fc):
        ss += f"{k}:{fc[k]}\n"
    ss += path
    if queries:
        parts = []
        for k in queries:
            val = queries[k]
            if isinstance(val, (list, tuple)):
                for x in val:
                    parts.append(k if x is None else f"{k}={x}")
            elif val is None:
                parts.append(k)
            else:
                parts.append(f"{k}={val}")
        ss += "\n" + "\n".join(sorted(parts))
    digest = hmac.new(secret.encode(), ss.encode(), hashlib.sha256).digest()
    return base64.b64encode(digest).decode()


class TestSigner(unittest.TestCase):
    def test_basic_no_fc_headers_no_query(self):
        hdrs = {"Date": "Mon, 01 Jan 2024 00:00:00 GMT", "sessionID": "abc"}
        self.assertEqual(
            signer.signature("SK", "GET", "/start", hdrs),
            _ref_sign("SK", "GET", "/start", hdrs),
        )

    def test_business_headers_excluded_from_signature(self):
        # sessionID / X-Browser-Cfg 非 x-fc- 前缀，不应影响签名
        base = {"Date": "Mon, 01 Jan 2024 00:00:00 GMT"}
        with_extra = dict(base, sessionID="s", **{"X-Browser-Cfg": "cfg"})
        self.assertEqual(
            signer.signature("SK", "GET", "/", with_extra),
            signer.signature("SK", "GET", "/", base),
        )

    def test_fc_headers_and_query(self):
        hdrs = {
            "Date": "Tue, 02 Jan 2024 03:04:05 GMT",
            "Content-Type": "application/json",
            "x-fc-security-token": "TKN",
            "x-fc-foo": "bar",
        }
        q = {"b": "2", "a": None, "c": ["y", "x"]}
        self.assertEqual(
            signer.signature("secret", "POST", "/v/x", hdrs, q),
            _ref_sign("secret", "POST", "/v/x", hdrs, q),
        )

    def test_sign_headers_integration(self):
        body = b'{"k":1}'
        H = signer.sign_headers(
            method="POST",
            url="https://h.fcapp.run/a/b?ignored=1",  # query 不自动入签
            access_key_id="AK", access_key_secret="S",
            extra_headers={"X-Browser-Cfg": "cfg"},
            security_token="ST", body=body,
            date="Wed, 03 Jan 2024 00:00:00 GMT",
        )
        exp_hdrs = {
            "Date": "Wed, 03 Jan 2024 00:00:00 GMT",
            "Content-MD5": signer.content_md5(body),
            "x-fc-security-token": "ST",
            "X-Browser-Cfg": "cfg",
        }
        self.assertEqual(H["Authorization"], "FC AK:" + _ref_sign("S", "POST", "/a/b", exp_hdrs))
        self.assertEqual(H["X-Browser-Cfg"], "cfg")
        self.assertIn("Date", H)

    def test_content_md5_empty(self):
        self.assertEqual(signer.content_md5(None), "")
        self.assertEqual(signer.content_md5(b""), "")
        self.assertTrue(signer.content_md5(b"x"))


if __name__ == "__main__":
    unittest.main()
