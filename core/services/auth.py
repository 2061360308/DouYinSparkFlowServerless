"""会话鉴权服务（异步）。整合 SessionService + WebSession 落库。

替代旧 web/auth.py 的会话读写：DB 会话 Cookie + CSRF。
"""

from __future__ import annotations

from core.db.domain_models import User, WebSession
from core.security import PasswordService, SessionService
from core.services import ValidationError
from core.timeutil import to_naive_utc, utcnow


class AuthService:
    def __init__(self, sessions: SessionService, passwords: PasswordService):
        self.sessions = sessions
        self.passwords = passwords

    async def create_session(self, user_id: str) -> tuple[str, WebSession]:
        ns = self.sessions.new_session()
        record = await WebSession.create(
            user_id=user_id,
            token_hash=ns.token_hash,
            csrf_token=ns.csrf_token,
            expires_at=ns.expires_at,
        )
        return ns.raw_cookie, record

    async def load(self, raw_cookie: str | None) -> tuple[User, WebSession] | None:
        if not raw_cookie:
            return None
        record = await WebSession.get_or_none(
            token_hash=self.sessions.token_hash(raw_cookie)
        )
        if record is None or to_naive_utc(record.expires_at) <= utcnow():
            return None
        user = await User.get_or_none(id=record.user_id)
        if user is None or user.status != "active":
            return None
        return user, record

    async def logout(self, record: WebSession) -> None:
        await record.delete()

    async def change_password(
        self, user: User, current_password: str, new_password: str, confirmation: str
    ) -> None:
        if not self.passwords.verify(user.password_hash, current_password):
            raise ValidationError("当前密码错误")
        if new_password != confirmation:
            raise ValidationError("两次输入的新密码不一致")
        try:
            hashed = self.passwords.hash(new_password)
        except ValueError as error:
            raise ValidationError("新密码至少需要 12 位") from error
        user.password_hash = hashed
        user.must_change_password = False
        await user.save(update_fields=["password_hash", "must_change_password", "updated_at"])
