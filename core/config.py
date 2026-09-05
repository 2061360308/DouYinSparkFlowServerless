"""运行配置（Vercel/serverless 友好）：全部来自环境变量，密钥用 base64。

与旧 spark_console.config 的区别：
- 加密密钥不再读文件，改从环境变量 base64 读取（Vercel 只读文件系统）；
- 去掉 worker/notifier/健康快照等相关项；邮件改请求内联发送。

必需环境变量：
- SPARK_COOKIE_KEY_B64   : 32 字节（base64），加密抖音 cookie / 登录输入
- SPARK_SESSION_KEY_B64  : >=32 字节（base64），会话 token 派生
启用邮件时另需：
- SPARK_PII_KEY_B64      : 32 字节（base64），加密邮箱等 PII
- RESEND_API_KEY / RESEND_FROM / SPARK_PUBLIC_BASE_URL(https)

开发便利：设 SPARK_DEV_INSECURE=1 时，缺失的密钥会用随机值临时生成
（仅用于本地冒烟，重启后无法解密旧数据，切勿用于生产）。
"""

from __future__ import annotations

import base64
import os
from dataclasses import dataclass, field
from typing import Mapping

_TRUE = {"1", "true", "yes", "on"}


def _decode_key(raw: str) -> bytes:
    try:
        return base64.b64decode(raw, validate=True)
    except Exception as error:  # noqa: BLE001
        raise ValueError("key must be valid base64") from error


@dataclass(frozen=True)
class Settings:
    cookie_key: bytes = field(repr=False)
    session_key: bytes = field(repr=False)
    pii_key: bytes | None = field(default=None, repr=False)
    secure_cookies: bool = True
    timezone: str = "Asia/Shanghai"
    email_enabled: bool = False
    public_base_url: str = ""
    resend_api_key: str = field(default="", repr=False)
    resend_from: str = ""
    service_token: str = field(default="", repr=False)
    dev_insecure: bool = False

    @classmethod
    def from_env(cls, environ: Mapping[str, str] | None = None) -> "Settings":
        environ = environ if environ is not None else os.environ
        dev_insecure = environ.get("SPARK_DEV_INSECURE", "").strip().lower() in _TRUE

        cookie_key = cls._load_key(environ, "SPARK_COOKIE_KEY_B64", 32, dev_insecure, exact=True)
        session_key = cls._load_key(environ, "SPARK_SESSION_KEY_B64", 32, dev_insecure, exact=False)

        email_enabled = environ.get("SPARK_EMAIL_ENABLED", "false").strip().lower() in _TRUE
        public_base_url = environ.get("SPARK_PUBLIC_BASE_URL", "").strip().rstrip("/")
        resend_api_key = environ.get("RESEND_API_KEY", "").strip()
        resend_from = environ.get("RESEND_FROM", "").strip()
        pii_key: bytes | None = None
        if email_enabled:
            pii_key = cls._load_key(environ, "SPARK_PII_KEY_B64", 32, dev_insecure, exact=True)
            if not resend_api_key or not resend_from:
                raise ValueError("email requires RESEND_API_KEY and RESEND_FROM")
            if not public_base_url.startswith("https://") and not dev_insecure:
                raise ValueError("SPARK_PUBLIC_BASE_URL must use HTTPS")

        secure_cookies = environ.get("SPARK_SECURE_COOKIES", "true").strip().lower() not in {
            "0", "false", "no", "off"
        }
        # 服务令牌：任务函数(FC/本地)访问 /api/internal/* 的机器身份。
        # dev_insecure 下若未提供则随机生成(仅本地冒烟；跨进程需显式设置同一值)。
        service_token = environ.get("SPARK_SERVICE_TOKEN", "").strip()
        if not service_token and dev_insecure:
            service_token = os.urandom(24).hex()
        return cls(
            cookie_key=cookie_key,
            session_key=session_key,
            pii_key=pii_key,
            secure_cookies=secure_cookies,
            timezone=environ.get("SPARK_TIMEZONE", "Asia/Shanghai"),
            email_enabled=email_enabled,
            public_base_url=public_base_url,
            resend_api_key=resend_api_key,
            resend_from=resend_from,
            service_token=service_token,
            dev_insecure=dev_insecure,
        )

    @staticmethod
    def _load_key(
        environ: Mapping[str, str],
        name: str,
        size: int,
        dev_insecure: bool,
        *,
        exact: bool,
    ) -> bytes:
        raw = environ.get(name, "").strip()
        if not raw:
            if dev_insecure:
                return os.urandom(size)
            raise ValueError(f"missing required setting: {name}")
        key = _decode_key(raw)
        invalid = len(key) != size if exact else len(key) < size
        if invalid:
            requirement = "exactly" if exact else "at least"
            raise ValueError(f"{name} must decode to {requirement} {size} bytes")
        return key
