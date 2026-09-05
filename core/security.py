"""口令哈希（Argon2）与会话/CSRF token。由 spark_console.security 迁移。

去除了对 ORM 的直接依赖：``SessionService.new_session`` 只产出落库所需的字段，
由调用方用 ``WebSession.create(...)`` 写入（异步 Tortoise）。
"""

from __future__ import annotations

import hashlib
import secrets
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone

from argon2 import PasswordHasher
from argon2.exceptions import InvalidHashError, VerifyMismatchError

from core.timeutil import utcnow


class PasswordService:
    def __init__(self) -> None:
        self._hasher = PasswordHasher()

    def hash(self, password: str) -> str:
        if len(password) < 12:
            raise ValueError("password must contain at least 12 characters")
        return self._hasher.hash(password)

    def verify(self, encoded: str, password: str) -> bool:
        try:
            return self._hasher.verify(encoded, password)
        except (VerifyMismatchError, InvalidHashError):
            return False


@dataclass(frozen=True)
class NewSession:
    """新建会话所需落库字段 + 下发给客户端的原始 cookie。"""

    raw_cookie: str
    token_hash: str
    csrf_token: str
    expires_at: datetime


class SessionService:
    def __init__(self, session_key: bytes, lifetime: timedelta = timedelta(hours=8)):
        if len(session_key) < 32:
            raise ValueError("session key must contain at least 32 bytes")
        self._key = session_key
        self._lifetime = lifetime

    @staticmethod
    def token_hash(raw_token: str) -> str:
        return hashlib.sha256(raw_token.encode("ascii")).hexdigest()

    def new_session(self, now: datetime | None = None) -> NewSession:
        issued_at = now or utcnow()
        raw = secrets.token_urlsafe(32)
        return NewSession(
            raw_cookie=raw,
            token_hash=self.token_hash(raw),
            csrf_token=secrets.token_urlsafe(32),
            expires_at=issued_at + self._lifetime,
        )

    def matches(self, raw_token: str, stored_hash: str) -> bool:
        return secrets.compare_digest(self.token_hash(raw_token), stored_hash)


class CsrfService:
    @staticmethod
    def issue() -> str:
        return secrets.token_urlsafe(32)

    @staticmethod
    def verify(expected: str, supplied: str) -> bool:
        return secrets.compare_digest(expected, supplied)
