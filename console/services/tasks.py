"""续火任务服务（异步）。由 spark_console.services.tasks 迁移。

不含 worker 相关的重登补跑逻辑（schedule_recent_safe_failures 属执行面）。
"""

from __future__ import annotations

import re
from datetime import datetime, timedelta, timezone
from zoneinfo import ZoneInfo

from tortoise.exceptions import IntegrityError

from db.console_models import (
    DouyinContactIdentity,
    SparkTask,
    SparkTaskTargetIdentity,
    User,
)
from console.services import Conflict, NotFound, ValidationError
from console.services.accounts import AccountService
from console.services.audit import AuditService
from console.services.task_capacity import TaskCapacityService


_TIME_RE = re.compile(r"^(?:[01]\d|2[0-3]):[0-5]\d$")


def _next_run_at(send_time: str) -> datetime:
    local_now = datetime.now(ZoneInfo("Asia/Shanghai"))
    hour, minute = map(int, send_time.split(":"))
    candidate = local_now.replace(hour=hour, minute=minute, second=0, microsecond=0)
    if candidate <= local_now:
        candidate += timedelta(days=1)
    # 存 naive-UTC
    return candidate.astimezone(timezone.utc).replace(tzinfo=None)


class TaskService:
    def __init__(self, accounts: AccountService, audit: AuditService | None = None):
        self.accounts = accounts
        self.audit = audit or AuditService()
        self.capacity = TaskCapacityService(self.audit)

    async def get_owned(self, owner_id: str, task_id: str) -> SparkTask:
        task = await SparkTask.get_or_none(id=task_id, owner_user_id=owner_id)
        if task is None:
            raise NotFound("task not found")
        return task

    async def list_owned(self, owner_id: str) -> list[SparkTask]:
        return list(
            await SparkTask.filter(owner_user_id=owner_id).order_by("send_time", "created_at")
        )

    @staticmethod
    def _validate(target_name: str, send_time: str, message_template: str) -> tuple[str, str]:
        target = target_name.strip()
        message = message_template.strip()
        if not target or len(target) > 64:
            raise ValidationError("好友名称须为 1–64 个字符")
        if not _TIME_RE.fullmatch(send_time):
            raise ValidationError("发送时间格式必须为 HH:MM")
        if not message or len(message) > 500:
            raise ValidationError("消息内容须为 1–500 个字符")
        return target, message

    async def _assert_target_belongs(self, account_id: str, sec_uid: str) -> None:
        if sec_uid and not await DouyinContactIdentity.filter(
            account_id=account_id, sec_uid=sec_uid
        ).exists():
            raise ValidationError("所选好友不属于当前抖音账号")

    async def create(
        self, owner_id: str, account_id: str, target_name: str,
        send_time: str, message_template: str, target_sec_uid: str | None = None,
    ) -> SparkTask:
        target, message = self._validate(target_name, send_time, message_template)
        account = await self.accounts.get_owned(owner_id, account_id)
        owner = await User.get_or_none(id=owner_id)
        if owner is None:
            raise NotFound("user not found")
        await self.capacity.assert_can_create(owner)
        await self.capacity.assert_slot_available(send_time)
        stable_target = str(target_sec_uid or "").strip()
        await self._assert_target_belongs(account.id, stable_target)
        try:
            task = await SparkTask.create(
                owner_user_id=owner_id,
                douyin_account_id=account.id,
                target_name=target,
                send_time=send_time,
                message_template=message,
                enabled=True,
                next_run_at=_next_run_at(send_time),
            )
            if stable_target:
                await SparkTaskTargetIdentity.create(task_id=task.id, sec_uid=stable_target)
        except IntegrityError as error:
            raise Conflict("相同账号、好友和时间的启用任务已存在") from error
        await self.audit.write(owner_id, "task.created", "spark_task", task.id)
        return task

    async def set_enabled_owned(self, owner_id: str, task_id: str, enabled: bool) -> SparkTask:
        task = await self.get_owned(owner_id, task_id)
        return await self.set_enabled(task, enabled, owner_id)

    async def set_enabled(self, task: SparkTask, enabled: bool, actor_id: str) -> SparkTask:
        if enabled and task.douyin_account_id is None:
            raise ValidationError("账号已删除，无法启用任务")
        if enabled and not task.enabled:
            owner = await User.get_or_none(id=task.owner_user_id)
            if owner is None:
                raise NotFound("user not found")
            await self.capacity.assert_can_enable(owner)
            await self.capacity.assert_slot_available(task.send_time, task.id)
        task.enabled = enabled
        try:
            await task.save(update_fields=["enabled", "updated_at"])
        except IntegrityError as error:
            raise Conflict("相同账号、好友和时间的启用任务已存在") from error
        await self.audit.write(
            actor_id, "task.enabled" if enabled else "task.disabled", "spark_task", task.id
        )
        return task

    async def update_owned(
        self, owner_id: str, task_id: str, account_id: str, target_name: str,
        send_time: str, message_template: str, target_sec_uid: str | None = None,
    ) -> SparkTask:
        task = await self.get_owned(owner_id, task_id)
        target, message = self._validate(target_name, send_time, message_template)
        account = await self.accounts.get_owned(owner_id, account_id)
        stable_target = str(target_sec_uid or "").strip()
        await self._assert_target_belongs(account.id, stable_target)
        if task.enabled:
            await self.capacity.assert_slot_available(send_time, task.id)
            duplicate = await SparkTask.filter(
                douyin_account_id=account.id, target_name=target,
                send_time=send_time, enabled=True,
            ).exclude(id=task.id).exists()
            if duplicate:
                raise Conflict("相同账号、好友和时间的启用任务已存在")
        task.douyin_account_id = account.id
        task.target_name = target
        task.send_time = send_time
        task.message_template = message
        task.next_run_at = _next_run_at(send_time)
        await task.save()

        binding = await SparkTaskTargetIdentity.get_or_none(task_id=task.id)
        if stable_target:
            if binding is None:
                await SparkTaskTargetIdentity.create(task_id=task.id, sec_uid=stable_target)
            else:
                binding.sec_uid = stable_target
                await binding.save(update_fields=["sec_uid"])
        elif binding is not None:
            await binding.delete()
        await self.audit.write(owner_id, "task.updated", "spark_task", task.id)
        return task

    async def delete_owned(self, owner_id: str, task_id: str) -> None:
        task = await self.get_owned(owner_id, task_id)
        await task.delete()
        await self.audit.write(owner_id, "task.deleted", "spark_task", task_id)
