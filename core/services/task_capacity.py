"""任务额度与四分钟安全间隔（异步）。由 spark_console.services.task_capacity 迁移。

规则保持一致：时间窗额度授予、启用任务数上限、保存任务数上限、发送时间需与
其它启用任务相隔 >= 4 分钟；额度过期自动暂停超额任务。
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from math import ceil
from zoneinfo import ZoneInfo

from tortoise.exceptions import IntegrityError
from tortoise.expressions import Q

from core.db.domain_models import (
    SparkTask,
    TaskQuotaGrant,
    TaskQuotaPolicy,
    TaskRun,
    User,
    UserTaskQuota,
)
from core.services import NotFound, ValidationError
from core.services.audit import AuditService
from core.timeutil import to_naive_utc, utcnow


MIN_TASK_LIMIT = 0
MAX_TASK_LIMIT = 100
MIN_SAVED_TASKS = 1
MAX_SAVED_TASKS = 500
SLOT_MINUTES = 4
MINUTES_PER_DAY = 24 * 60
SHANGHAI = ZoneInfo("Asia/Shanghai")


@dataclass(frozen=True)
class SlotAvailability:
    available: bool
    remaining: int
    suggestions: tuple[str, ...]


def _aware(value: datetime) -> datetime:
    # 全程 naive-UTC：归一化（保留旧函数名，减少调用点改动）
    return to_naive_utc(value)


class TaskCapacityService:
    def __init__(self, audit: AuditService | None = None):
        self.audit = audit or AuditService()

    async def policy(self) -> TaskQuotaPolicy:
        policy = await TaskQuotaPolicy.get_or_none(id=1)
        if policy is None:
            raise ValidationError("任务额度策略尚未初始化")
        return policy

    async def bootstrap_user(
        self,
        user: User,
        use_current_policy: bool = False,
        effective_at: datetime | None = None,
    ) -> TaskQuotaGrant | None:
        if user.role == "admin":
            return None
        if await TaskQuotaGrant.filter(user_id=user.id).exists():
            return None
        policy = await self.policy()
        legacy = await UserTaskQuota.get_or_none(user_id=user.id)
        amount = legacy.task_limit if legacy is not None else policy.default_amount
        current = _aware(effective_at or utcnow())
        created_at = _aware(user.created_at) if user.created_at else current
        starts_at = current if use_current_policy else min(created_at, current)
        expires_at = None
        if use_current_policy and policy.default_duration_days is not None:
            expires_at = starts_at + timedelta(days=policy.default_duration_days)
        try:
            return await TaskQuotaGrant.create(
                user_id=user.id,
                amount=amount,
                starts_at=starts_at,
                expires_at=expires_at,
                label="注册基础额度",
                is_initial=True,
            )
        except IntegrityError:
            return await TaskQuotaGrant.filter(
                user_id=user.id, is_initial=True
            ).first()

    async def grants_for(self, user_id: str) -> list[TaskQuotaGrant]:
        user = await User.get_or_none(id=user_id)
        if user is None:
            raise NotFound("user not found")
        await self.bootstrap_user(user)
        return list(
            await TaskQuotaGrant.filter(user_id=user_id).order_by(
                "starts_at", "created_at"
            )
        )

    async def limit_for(self, user: User, at: datetime | None = None) -> int | None:
        if user.role == "admin":
            return None
        current = _aware(at or utcnow())
        await self.bootstrap_user(user, effective_at=current)
        grants = await TaskQuotaGrant.filter(
            user_id=user.id,
            revoked_at__isnull=True,
            starts_at__lte=current,
        ).filter(Q(expires_at__isnull=True) | Q(expires_at__gt=current))
        return sum(grant.amount for grant in grants)

    async def active_usage_for(self, user_id: str) -> int:
        return await SparkTask.filter(owner_user_id=user_id, enabled=True).count()

    async def saved_usage_for(self, user_id: str) -> int:
        return await SparkTask.filter(owner_user_id=user_id).count()

    async def summary_for(self, user: User, at: datetime | None = None) -> dict:
        current = _aware(at or utcnow())
        grants = await self.grants_for(user.id) if user.role != "admin" else []
        grant_items = []
        for grant in grants:
            start = _aware(grant.starts_at)
            end = _aware(grant.expires_at) if grant.expires_at else None
            revoked = _aware(grant.revoked_at) if grant.revoked_at else None
            if revoked is not None:
                status = "revoked"
            elif current < start:
                status = "future"
            elif end is not None and current >= end:
                status = "expired"
            else:
                status = "active"
            days_remaining = None
            if status == "active" and end is not None:
                days_remaining = max(1, ceil((end - current).total_seconds() / 86400))
                if end - current <= timedelta(days=7):
                    status = "expiring"
            grant_items.append(
                {
                    "id": grant.id,
                    "amount": grant.amount,
                    "label": grant.label,
                    "starts_at": start.isoformat(),
                    "expires_at": end.isoformat() if end else None,
                    "status": status,
                    "days_remaining": days_remaining,
                }
            )
        policy = await self.policy()
        return {
            "limit": await self.limit_for(user, current),
            "active_usage": await self.active_usage_for(user.id),
            "saved_usage": await self.saved_usage_for(user.id),
            "max_saved_tasks": policy.max_saved_tasks,
            "grants": grant_items,
        }

    async def assert_can_create(self, user: User) -> None:
        policy = await self.policy()
        saved = await self.saved_usage_for(user.id)
        if user.role != "admin" and saved >= policy.max_saved_tasks:
            raise ValidationError(f"普通用户最多保存 {policy.max_saved_tasks} 个任务")
        limit = await self.limit_for(user)
        if limit is None:
            return
        usage = await self.active_usage_for(user.id)
        if usage >= limit:
            raise ValidationError(
                f"当前启用任务 {usage}/{limit}，请暂停任务或联系管理员增加额度"
            )

    async def assert_can_enable(self, user: User) -> None:
        limit = await self.limit_for(user)
        if limit is None:
            return
        usage = await self.active_usage_for(user.id)
        if usage >= limit:
            raise ValidationError(
                f"当前启用任务 {usage}/{limit}，请先暂停其他任务或联系管理员增加额度"
            )

    async def reconcile_user(self, user_id: str, at: datetime | None = None) -> list[str]:
        user = await User.get_or_none(id=user_id)
        if user is None:
            raise NotFound("user not found")
        limit = await self.limit_for(user, at)
        if limit is None:
            return []
        enabled = list(
            await SparkTask.filter(owner_user_id=user_id, enabled=True).order_by(
                "created_at", "id"
            )
        )
        excess = enabled[limit:]
        for task in excess:
            task.enabled = False
            task.next_run_at = None
            await task.save(update_fields=["enabled", "next_run_at", "updated_at"])
            await self.audit.write(
                None,
                "task.quota_auto_paused",
                "spark_task",
                task.id,
                detail=f"user_id={user_id};effective_limit={limit}",
            )
        return [task.id for task in excess]

    async def reconcile_all(self, at: datetime | None = None) -> list[str]:
        user_ids = (
            await SparkTask.filter(enabled=True, owner_user__role__not="admin")
            .distinct()
            .values_list("owner_user_id", flat=True)
        )
        paused: list[str] = []
        for user_id in user_ids:
            paused.extend(await self.reconcile_user(user_id, at))
        return paused

    # ---- 管理员额度维护 ----
    async def update_policy(
        self, actor_id: str, default_amount: int, default_duration_days: int | None, max_saved_tasks: int
    ) -> TaskQuotaPolicy:
        actor = await User.get_or_none(id=actor_id)
        if actor is None or actor.role != "admin":
            raise NotFound("user not found")
        if not MIN_TASK_LIMIT <= default_amount <= MAX_TASK_LIMIT:
            raise ValidationError("默认任务额度须为 0–100")
        if default_duration_days is not None and not 1 <= default_duration_days <= 3650:
            raise ValidationError("默认有效期须为 1–3650 天")
        if not MIN_SAVED_TASKS <= max_saved_tasks <= MAX_SAVED_TASKS:
            raise ValidationError("任务保存上限须为 1–500")
        policy = await self.policy()
        policy.default_amount = default_amount
        policy.default_duration_days = default_duration_days
        policy.max_saved_tasks = max_saved_tasks
        await policy.save()
        await self.audit.write(actor_id, "quota.policy_updated", "task_quota_policy", str(policy.id))
        return policy

    async def grant(
        self, actor_id: str, user_id: str, amount: int,
        starts_at: datetime, expires_at: datetime | None, label: str,
    ) -> TaskQuotaGrant:
        actor = await User.get_or_none(id=actor_id)
        target = await User.get_or_none(id=user_id)
        if actor is None or actor.role != "admin" or target is None:
            raise NotFound("user not found")
        if target.role == "admin":
            raise ValidationError("管理员账号无需设置任务额度")
        if not 1 <= amount <= MAX_TASK_LIMIT:
            raise ValidationError("单次增加额度须为 1–100")
        start = _aware(starts_at)
        end = _aware(expires_at) if expires_at is not None else None
        if end is not None and end <= start:
            raise ValidationError("额度到期时间必须晚于开始时间")
        clean_label = label.strip()
        if not clean_label or len(clean_label) > 64:
            raise ValidationError("额度名称须为 1–64 个字符")
        await self.bootstrap_user(target)
        grant = await TaskQuotaGrant.create(
            user_id=user_id, amount=amount, starts_at=start, expires_at=end,
            label=clean_label, created_by_user_id=actor_id,
        )
        await self.audit.write(actor_id, "quota.granted", "task_quota_grant", grant.id)
        return grant

    async def update_grant(
        self, actor_id: str, grant_id: str, amount: int,
        starts_at: datetime, expires_at: datetime | None, label: str,
    ) -> TaskQuotaGrant:
        actor = await User.get_or_none(id=actor_id)
        grant = await TaskQuotaGrant.get_or_none(id=grant_id)
        if actor is None or actor.role != "admin" or grant is None:
            raise NotFound("quota grant not found")
        if grant.revoked_at is not None:
            raise ValidationError("已撤销的额度不能修改")
        if not 1 <= amount <= MAX_TASK_LIMIT:
            raise ValidationError("单条额度须为 1–100")
        start = _aware(starts_at)
        end = _aware(expires_at) if expires_at is not None else None
        if end is not None and end <= start:
            raise ValidationError("额度到期时间必须晚于开始时间")
        clean_label = label.strip()
        if not clean_label or len(clean_label) > 64:
            raise ValidationError("额度名称须为 1–64 个字符")
        grant.amount = amount
        grant.starts_at = start
        grant.expires_at = end
        grant.label = clean_label
        await grant.save()
        await self.audit.write(actor_id, "quota.updated", "task_quota_grant", grant.id)
        await self.reconcile_user(grant.user_id)
        return grant

    async def revoke(self, actor_id: str, grant_id: str, at: datetime | None = None) -> list[str]:
        actor = await User.get_or_none(id=actor_id)
        grant = await TaskQuotaGrant.get_or_none(id=grant_id)
        if actor is None or actor.role != "admin" or grant is None:
            raise NotFound("quota grant not found")
        if grant.revoked_at is not None:
            raise ValidationError("该额度已经撤销")
        current = _aware(at or utcnow())
        grant.revoked_at = current
        await grant.save(update_fields=["revoked_at", "updated_at"])
        await self.audit.write(actor_id, "quota.revoked", "task_quota_grant", grant.id)
        return await self.reconcile_user(grant.user_id, current)

    async def set_limit(self, actor_id: str, user_id: str, limit: int) -> TaskQuotaGrant:
        actor = await User.get_or_none(id=actor_id)
        target = await User.get_or_none(id=user_id)
        if actor is None or actor.role != "admin" or target is None:
            raise NotFound("user not found")
        if target.role == "admin":
            raise ValidationError("管理员账号无需设置任务上限")
        if limit < 1 or limit > MAX_TASK_LIMIT:
            raise ValidationError("任务上限须为 1–100")
        grants = await self.grants_for(user_id)
        quota = grants[0]
        quota.amount = limit
        await quota.save(update_fields=["amount", "updated_at"])
        await self.audit.write(actor_id, "user.task_limit_updated", "user", user_id)
        return quota

    # ---- 四分钟安全间隔 ----
    @staticmethod
    def bucket_for(send_time: str) -> int:
        try:
            hour_text, minute_text = send_time.split(":", 1)
            hour, minute = int(hour_text), int(minute_text)
        except (AttributeError, TypeError, ValueError):
            raise ValidationError("发送时间格式必须为 HH:MM") from None
        if not (0 <= hour <= 23 and 0 <= minute <= 59):
            raise ValidationError("发送时间格式必须为 HH:MM")
        return hour * 60 + minute

    @staticmethod
    def time_for_bucket(bucket: int) -> str:
        minutes = bucket % MINUTES_PER_DAY
        return f"{minutes // 60:02d}:{minutes % 60:02d}"

    @staticmethod
    def _minutes_apart(left: int, right: int) -> int:
        distance = abs(left - right)
        return min(distance, MINUTES_PER_DAY - distance)

    async def occupied_buckets(self, exclude_task_id: str | None = None) -> set[int]:
        query = SparkTask.filter(enabled=True)
        if exclude_task_id:
            query = query.exclude(id=exclude_task_id)
        send_times = await query.values_list("send_time", flat=True)
        return {self.bucket_for(value) for value in send_times}

    async def next_available_times(
        self, send_time: str, count: int = 3, exclude_task_id: str | None = None
    ) -> tuple[str, ...]:
        origin = self.bucket_for(send_time)
        occupied = await self.occupied_buckets(exclude_task_id)
        suggestions: list[str] = []
        seen = {origin}
        for distance in range(1, MINUTES_PER_DAY):
            for candidate in (
                (origin - distance) % MINUTES_PER_DAY,
                (origin + distance) % MINUTES_PER_DAY,
            ):
                if candidate in seen:
                    continue
                seen.add(candidate)
                if any(self._minutes_apart(candidate, value) < SLOT_MINUTES for value in occupied):
                    continue
                suggestions.append(self.time_for_bucket(candidate))
                if len(suggestions) == count:
                    return tuple(suggestions)
        return tuple(suggestions)

    async def availability(self, send_time: str, exclude_task_id: str | None = None) -> SlotAvailability:
        bucket = self.bucket_for(send_time)
        occupied = await self.occupied_buckets(exclude_task_id)
        available = all(self._minutes_apart(bucket, value) >= SLOT_MINUTES for value in occupied)
        return SlotAvailability(
            available=available,
            remaining=1 if available else 0,
            suggestions=() if available else await self.next_available_times(send_time, 3, exclude_task_id),
        )

    async def assert_slot_available(self, send_time: str, exclude_task_id: str | None = None) -> None:
        if not (await self.availability(send_time, exclude_task_id)).available:
            raise ValidationError("该时间不满足四分钟安全间隔，请选择推荐时间")
