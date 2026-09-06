"""审计事件与限流记录模型。"""

from __future__ import annotations

from tortoise import fields, models

from .base import uuid_string


class AuditEvent(models.Model):
    id = fields.CharField(max_length=36, primary_key=True, default=uuid_string)
    actor_user_id = fields.CharField(max_length=36, null=True, db_index=True)
    action = fields.CharField(max_length=64)
    resource_type = fields.CharField(max_length=32)
    resource_id = fields.CharField(max_length=36, null=True)
    detail = fields.CharField(max_length=240, null=True)
    created_at = fields.DatetimeField(auto_now_add=True)

    class Meta:
        table = "audit_events"


class RateLimitAttempt(models.Model):
    """DB 版失败/请求限流（替代原内存 FailedAttemptLimiter，跨无状态实例正确）。

    每次尝试插入一行，按 (scope, key, created_at) 在时间窗内计数，过期行惰性清理。
    """

    id = fields.IntField(primary_key=True)
    scope = fields.CharField(max_length=64)
    key = fields.CharField(max_length=190)
    created_at = fields.DatetimeField(auto_now_add=True)

    class Meta:
        table = "rate_limit_attempts"
        indexes = (("scope", "key", "created_at"),)
