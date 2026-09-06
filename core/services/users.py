"""用户服务（异步）。由 spark_console.services.users 迁移。

去除 UserNotification 依赖；删除用户时级联清理其任务/账号/会话。
"""

from __future__ import annotations

import secrets
import string

from core.db.models import DouyinAccount, SparkTask, User, WebSession
from core.security import PasswordService
from core.services import Conflict, NotFound, ValidationError
from core.services.audit import AuditService


def validate_registration_username(username: str) -> str:
    name = username.strip().lower()
    if not (3 <= len(name) <= 32) or not all(
        character.isalnum() or character in "_-" for character in name
    ):
        raise ValidationError("用户名须为 3–32 位字母、数字、下划线或短横线")
    return name


def validate_registration_password(password: str) -> None:
    if len(password) < 10:
        raise ValidationError("密码至少需要 10 位")
    if not any(character.isalpha() for character in password):
        raise ValidationError("密码必须包含至少一个字母")
    if not any(character.isdigit() for character in password):
        raise ValidationError("密码必须包含至少一个数字")


class UserService:
    def __init__(self, passwords: PasswordService, audit: AuditService | None = None):
        self.passwords = passwords
        self.audit = audit or AuditService()

    @staticmethod
    def temporary_password() -> str:
        alphabet = string.ascii_letters + string.digits + "!@#$%"
        return "".join(secrets.choice(alphabet) for _ in range(18))

    async def create(
        self, username: str, password: str | None = None, role: str = "user"
    ) -> tuple[User, str]:
        name = validate_registration_username(username)
        if role not in {"user", "admin"}:
            raise ValidationError("invalid role")
        if await User.filter(username=name).exists():
            raise Conflict("该用户名不可用，请更换")
        temporary = password or self.temporary_password()
        user = await User.create(
            username=name,
            password_hash=self.passwords.hash(temporary),
            role=role,
            must_change_password=True,
        )
        if role == "user":
            from core.services.task_capacity import TaskCapacityService

            await TaskCapacityService(self.audit).bootstrap_user(user, use_current_policy=True)
        await self.audit.write(None, "user.created", "user", user.id)
        return user, temporary

    async def authenticate(self, username: str, password: str) -> User | None:
        user = await User.get_or_none(username=username.strip().lower())
        if user is None or user.status != "active":
            return None
        if not self.passwords.verify(user.password_hash, password):
            user.failed_login_count += 1
            await user.save(update_fields=["failed_login_count", "updated_at"])
            return None
        user.failed_login_count = 0
        user.locked_until = None
        await user.save(update_fields=["failed_login_count", "locked_until", "updated_at"])
        return user

    async def reset_password(self, actor_id: str, user_id: str) -> str:
        user = await User.get_or_none(id=user_id)
        if user is None:
            raise NotFound("user not found")
        temporary = self.temporary_password()
        user.password_hash = self.passwords.hash(temporary)
        user.must_change_password = True
        await user.save(update_fields=["password_hash", "must_change_password", "updated_at"])
        await WebSession.filter(user_id=user.id).delete()
        await self.audit.write(actor_id, "user.password_reset", "user", user.id)
        return temporary

    async def set_disabled(self, actor_id: str, user_id: str, disabled: bool) -> User:
        user = await User.get_or_none(id=user_id)
        if user is None:
            raise NotFound("user not found")
        user.status = "disabled" if disabled else "active"
        await user.save(update_fields=["status", "updated_at"])
        await self.audit.write(
            actor_id, "user.disabled" if disabled else "user.enabled", "user", user.id
        )
        return user

    async def delete(self, actor_id: str, user_id: str, confirmation: str) -> None:
        user = await User.get_or_none(id=user_id)
        if user is None:
            raise NotFound("user not found")
        if user.id == actor_id:
            raise ValidationError("不能删除当前管理员账号")
        if confirmation != user.username:
            raise ValidationError("确认用户名不匹配")
        await SparkTask.filter(owner_user_id=user.id).delete()
        await DouyinAccount.filter(owner_user_id=user.id).delete()
        await WebSession.filter(user_id=user.id).delete()
        await user.delete()
        await self.audit.write(actor_id, "user.deleted", "user", user_id)
