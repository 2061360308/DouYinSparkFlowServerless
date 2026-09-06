"""任务额度策略与授予记录模型。"""

from __future__ import annotations

from tortoise import fields, models

from .base import uuid_string


class TaskQuotaPolicy(models.Model):
    id = fields.IntField(primary_key=True)
    default_amount = fields.IntField()
    default_duration_days = fields.IntField(null=True)
    max_saved_tasks = fields.IntField()
    updated_at = fields.DatetimeField(auto_now=True)

    class Meta:
        table = "task_quota_policy"


class TaskQuotaGrant(models.Model):
    id = fields.CharField(max_length=36, primary_key=True, default=uuid_string)
    user = fields.ForeignKeyField(
        "models.User", related_name="quota_grants",
        on_delete=fields.CASCADE, db_index=True,
    )
    amount = fields.IntField()
    starts_at = fields.DatetimeField()
    expires_at = fields.DatetimeField(null=True)
    revoked_at = fields.DatetimeField(null=True)
    label = fields.CharField(max_length=64)
    # 每用户仅一条初始额度：部分唯一索引 (user_id) WHERE is_initial 在 init 补建
    is_initial = fields.BooleanField(default=False)
    created_by_user = fields.ForeignKeyField(
        "models.User", related_name="created_quota_grants",
        on_delete=fields.SET_NULL, null=True,
    )
    created_at = fields.DatetimeField(auto_now_add=True)
    updated_at = fields.DatetimeField(auto_now=True)

    class Meta:
        table = "task_quota_grants"
        indexes = (("user_id", "starts_at", "expires_at"),)
