"""控制台业务模型（由 spark_console 的 SQLAlchemy 模型迁移为 Tortoise-ORM）。

迁移范围与取舍（本期）：
- 保留：用户/抖音账号/额度(策略·授予)/会话·扫码登录/任务·执行记录/审计/
  注册与邮箱验证/系统开关。
- 删除（无 worker、邮件改请求内联发送后成为摆设）：notification_events 发件箱、
  email_action_tokens、notification_preferences、user_notifications、worker_lock。
- 浏览器执行面（发消息 / 扫码登录）本期只出页面，不落执行进程。

约定：
- 主键 UUID 用 ``CharField(pk=True, default=uuid_string)``；SQLAlchemy 里的复合主键
  （会话/联系人）改为代理自增主键 + ``unique_together``（Tortoise 不支持复合主键）。
- 外键字段命名保持业务语义：如 ``owner_user`` → 数据库列/属性 ``owner_user_id``。
- 时间统一 UTC（TORTOISE_ORM 开启 ``use_tz``）。
- 部分唯一索引（带 WHERE）Tortoise 不支持声明式定义，见 ``db.init_db`` 中的原生 SQL 补建。
"""

from __future__ import annotations

import uuid
from enum import StrEnum

from tortoise import fields, models


def uuid_string() -> str:
    return str(uuid.uuid4())


class ScanStatus(StrEnum):
    QUEUED = "queued"
    LOADING_QR = "loading_qr"
    AWAITING_SCAN = "awaiting_scan"
    CONFIRMING = "confirming"
    SUCCEEDED = "succeeded"
    FAILED = "failed"
    EXPIRED = "expired"
    CANCELLED = "cancelled"


class User(models.Model):
    id = fields.CharField(max_length=36, pk=True, default=uuid_string)
    username = fields.CharField(max_length=32, unique=True)
    password_hash = fields.TextField()
    role = fields.CharField(max_length=16, default="user")
    status = fields.CharField(max_length=16, default="active")
    must_change_password = fields.BooleanField(default=True)
    failed_login_count = fields.IntField(default=0)
    locked_until = fields.DatetimeField(null=True)
    email_ciphertext = fields.BinaryField(null=True)
    email_nonce = fields.BinaryField(null=True)
    # 非空时唯一：部分唯一索引在 init 里用原生 SQL 补建
    email_lookup_hash = fields.CharField(max_length=64, null=True)
    email_verified_at = fields.DatetimeField(null=True)
    email_updated_at = fields.DatetimeField(null=True)
    created_at = fields.DatetimeField(auto_now_add=True)
    updated_at = fields.DatetimeField(auto_now=True)

    class Meta:
        table = "users"


class DouyinAccount(models.Model):
    id = fields.CharField(max_length=36, pk=True, default=uuid_string)
    owner_user = fields.ForeignKeyField(
        "models.User", related_name="douyin_accounts",
        on_delete=fields.CASCADE, index=True,
    )
    display_name = fields.CharField(max_length=64)
    encrypted_cookies = fields.BinaryField()
    cookie_nonce = fields.BinaryField()
    cookie_version = fields.IntField(default=1)
    validation_state = fields.CharField(max_length=16, default="unknown")
    last_verified_at = fields.DatetimeField(null=True)
    invalidated_at = fields.DatetimeField(null=True)
    invalid_reason_code = fields.CharField(max_length=48, null=True)
    auth_incident_id = fields.CharField(max_length=36, null=True)
    created_at = fields.DatetimeField(auto_now_add=True)
    updated_at = fields.DatetimeField(auto_now=True)

    class Meta:
        table = "douyin_accounts"


class UserTaskQuota(models.Model):
    user = fields.OneToOneField(
        "models.User", related_name="task_quota",
        on_delete=fields.CASCADE, pk=True,
    )
    task_limit = fields.IntField(default=5)
    updated_at = fields.DatetimeField(auto_now=True)

    class Meta:
        table = "user_task_quotas"


class TaskQuotaPolicy(models.Model):
    id = fields.IntField(pk=True)
    default_amount = fields.IntField()
    default_duration_days = fields.IntField(null=True)
    max_saved_tasks = fields.IntField()
    updated_at = fields.DatetimeField(auto_now=True)

    class Meta:
        table = "task_quota_policy"


class TaskQuotaGrant(models.Model):
    id = fields.CharField(max_length=36, pk=True, default=uuid_string)
    user = fields.ForeignKeyField(
        "models.User", related_name="quota_grants",
        on_delete=fields.CASCADE, index=True,
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


class DouyinConversation(models.Model):
    # 原复合主键 (account_id, display_name) → 代理主键 + unique_together
    id = fields.IntField(pk=True)
    account = fields.ForeignKeyField(
        "models.DouyinAccount", related_name="conversations",
        on_delete=fields.CASCADE,
    )
    display_name = fields.CharField(max_length=256)
    discovered_at = fields.DatetimeField(auto_now_add=True)

    class Meta:
        table = "douyin_conversations"
        unique_together = (("account", "display_name"),)


class DouyinContactIdentity(models.Model):
    id = fields.IntField(pk=True)
    account = fields.ForeignKeyField(
        "models.DouyinAccount", related_name="contacts",
        on_delete=fields.CASCADE,
    )
    sec_uid = fields.CharField(max_length=256)
    short_id = fields.CharField(max_length=64, null=True)
    unique_id = fields.CharField(max_length=128, null=True)
    nickname = fields.CharField(max_length=256, null=True)
    remark_name = fields.CharField(max_length=256, null=True)
    discovered_at = fields.DatetimeField(auto_now_add=True)

    class Meta:
        table = "douyin_contact_identities"
        unique_together = (("account", "sec_uid"),)


class DouyinAccountIdentity(models.Model):
    account = fields.OneToOneField(
        "models.DouyinAccount", related_name="identity",
        on_delete=fields.CASCADE, pk=True,
    )
    douyin_unique_id = fields.CharField(max_length=64, null=True)
    created_at = fields.DatetimeField(auto_now_add=True)

    class Meta:
        table = "douyin_account_identities"


class InviteCode(models.Model):
    id = fields.CharField(max_length=36, pk=True, default=uuid_string)
    code_hash = fields.CharField(max_length=64, unique=True)
    created_by_user = fields.ForeignKeyField(
        "models.User", related_name="invites_created",
        on_delete=fields.SET_NULL, null=True,
    )
    expires_at = fields.DatetimeField()
    used_by_user = fields.ForeignKeyField(
        "models.User", related_name="invites_used",
        on_delete=fields.SET_NULL, null=True,
    )
    used_at = fields.DatetimeField(null=True)
    revoked_at = fields.DatetimeField(null=True)
    created_at = fields.DatetimeField(auto_now_add=True)

    class Meta:
        table = "invite_codes"


class InviteCodeSecret(models.Model):
    invite = fields.OneToOneField(
        "models.InviteCode", related_name="secret",
        on_delete=fields.CASCADE, pk=True,
    )
    ciphertext = fields.BinaryField()
    nonce = fields.BinaryField()

    class Meta:
        table = "invite_code_secrets"


class DouyinLoginSession(models.Model):
    id = fields.CharField(max_length=36, pk=True, default=uuid_string)
    owner_user = fields.ForeignKeyField(
        "models.User", related_name="login_sessions",
        on_delete=fields.CASCADE, index=True,
    )
    slot = fields.CharField(max_length=16, unique=True, null=True)
    status = fields.CharField(max_length=24, default=ScanStatus.QUEUED.value)
    qr_png = fields.BinaryField(null=True)
    qr_crop_png = fields.BinaryField(null=True)
    account = fields.ForeignKeyField(
        "models.DouyinAccount", related_name="login_sessions",
        on_delete=fields.SET_NULL, null=True,
    )
    error_code = fields.CharField(max_length=48, null=True)
    expires_at = fields.DatetimeField()
    created_at = fields.DatetimeField(auto_now_add=True)
    updated_at = fields.DatetimeField(auto_now=True)
    finished_at = fields.DatetimeField(null=True)

    class Meta:
        table = "douyin_login_sessions"


class DouyinLoginAction(models.Model):
    id = fields.IntField(pk=True)
    scan = fields.ForeignKeyField(
        "models.DouyinLoginSession", related_name="actions",
        on_delete=fields.CASCADE, index=True,
    )
    kind = fields.CharField(max_length=16)
    x_million = fields.IntField()
    y_million = fields.IntField()
    created_at = fields.DatetimeField(auto_now_add=True)
    consumed_at = fields.DatetimeField(null=True)

    class Meta:
        table = "douyin_login_actions"


class DouyinLoginInput(models.Model):
    id = fields.IntField(pk=True)
    scan = fields.ForeignKeyField(
        "models.DouyinLoginSession", related_name="inputs",
        on_delete=fields.CASCADE, index=True,
    )
    ciphertext = fields.BinaryField(null=True)
    nonce = fields.BinaryField(null=True)
    created_at = fields.DatetimeField(auto_now_add=True)
    consumed_at = fields.DatetimeField(null=True)

    class Meta:
        table = "douyin_login_inputs"


class SparkTask(models.Model):
    id = fields.CharField(max_length=36, pk=True, default=uuid_string)
    owner_user = fields.ForeignKeyField(
        "models.User", related_name="tasks",
        on_delete=fields.CASCADE, index=True,
    )
    douyin_account = fields.ForeignKeyField(
        "models.DouyinAccount", related_name="tasks",
        on_delete=fields.SET_NULL, null=True, index=True,
    )
    target_name = fields.CharField(max_length=64)
    send_time = fields.CharField(max_length=5)
    message_template = fields.CharField(max_length=500)
    enabled = fields.BooleanField(default=True)
    next_run_at = fields.DatetimeField(null=True, index=True)
    created_at = fields.DatetimeField(auto_now_add=True)
    updated_at = fields.DatetimeField(auto_now=True)

    class Meta:
        table = "spark_tasks"
        # 启用中的 (账号,目标,时间) 唯一：部分唯一索引 WHERE enabled 在 init 补建


class SparkTaskTargetIdentity(models.Model):
    task = fields.OneToOneField(
        "models.SparkTask", related_name="target_identity",
        on_delete=fields.CASCADE, pk=True,
    )
    sec_uid = fields.CharField(max_length=256)
    created_at = fields.DatetimeField(auto_now_add=True)

    class Meta:
        table = "spark_task_target_identities"


class TaskRun(models.Model):
    id = fields.CharField(max_length=36, pk=True, default=uuid_string)
    task = fields.ForeignKeyField(
        "models.SparkTask", related_name="runs",
        on_delete=fields.CASCADE, index=True,
    )
    scheduled_for = fields.DatetimeField()
    status = fields.CharField(max_length=16, default="queued")
    stage = fields.CharField(max_length=24, default="queued")
    started_at = fields.DatetimeField(null=True)
    finished_at = fields.DatetimeField(null=True)
    error_code = fields.CharField(max_length=48, null=True)
    error_summary = fields.CharField(max_length=240, null=True)
    message_digest = fields.CharField(max_length=64, null=True)

    class Meta:
        table = "task_runs"
        unique_together = (("task", "scheduled_for"),)


class WebSession(models.Model):
    id = fields.CharField(max_length=36, pk=True, default=uuid_string)
    user = fields.ForeignKeyField(
        "models.User", related_name="web_sessions",
        on_delete=fields.CASCADE, index=True,
    )
    token_hash = fields.CharField(max_length=64, unique=True)
    csrf_token = fields.CharField(max_length=64)
    expires_at = fields.DatetimeField()
    created_at = fields.DatetimeField(auto_now_add=True)

    class Meta:
        table = "web_sessions"


class AuditEvent(models.Model):
    id = fields.CharField(max_length=36, pk=True, default=uuid_string)
    actor_user_id = fields.CharField(max_length=36, null=True, index=True)
    action = fields.CharField(max_length=64)
    resource_type = fields.CharField(max_length=32)
    resource_id = fields.CharField(max_length=36, null=True)
    detail = fields.CharField(max_length=240, null=True)
    created_at = fields.DatetimeField(auto_now_add=True)

    class Meta:
        table = "audit_events"


class PendingRegistration(models.Model):
    id = fields.CharField(max_length=36, pk=True, default=uuid_string)
    username = fields.CharField(max_length=32, index=True)
    password_hash = fields.TextField()
    invite = fields.ForeignKeyField(
        "models.InviteCode", related_name="pending_registrations",
        on_delete=fields.CASCADE, index=True,
    )
    email_ciphertext = fields.BinaryField()
    email_nonce = fields.BinaryField()
    email_lookup_hash = fields.CharField(max_length=64, index=True)
    code_hash = fields.CharField(max_length=64)
    failed_attempts = fields.IntField(default=0)
    send_count = fields.IntField(default=1)
    client_key_hash = fields.CharField(max_length=64)
    code_expires_at = fields.DatetimeField()
    resend_available_at = fields.DatetimeField()
    expires_at = fields.DatetimeField(index=True)
    created_at = fields.DatetimeField(auto_now_add=True)
    updated_at = fields.DatetimeField(auto_now=True)

    class Meta:
        table = "pending_registrations"


class EmailVerificationRequest(models.Model):
    id = fields.CharField(max_length=36, pk=True, default=uuid_string)
    user = fields.ForeignKeyField(
        "models.User", related_name="email_verifications",
        on_delete=fields.CASCADE, index=True,
    )
    purpose = fields.CharField(max_length=24)
    email_ciphertext = fields.BinaryField()
    email_nonce = fields.BinaryField()
    email_lookup_hash = fields.CharField(max_length=64, index=True)
    code_hash = fields.CharField(max_length=64)
    failed_attempts = fields.IntField(default=0)
    send_count = fields.IntField(default=1)
    code_expires_at = fields.DatetimeField()
    resend_available_at = fields.DatetimeField()
    expires_at = fields.DatetimeField(index=True)
    consumed_at = fields.DatetimeField(null=True)
    created_at = fields.DatetimeField(auto_now_add=True)

    class Meta:
        table = "email_verification_requests"


class AppSetting(models.Model):
    key = fields.CharField(max_length=64, pk=True)
    value = fields.CharField(max_length=240)
    updated_at = fields.DatetimeField(auto_now=True)

    class Meta:
        table = "app_settings"


class RateLimitAttempt(models.Model):
    """DB 版失败/请求限流（替代原内存 FailedAttemptLimiter，跨无状态实例正确）。

    每次尝试插入一行，按 (scope, key, created_at) 在时间窗内计数，过期行惰性清理。
    """

    id = fields.IntField(pk=True)
    scope = fields.CharField(max_length=64)
    key = fields.CharField(max_length=190)
    created_at = fields.DatetimeField(auto_now_add=True)

    class Meta:
        table = "rate_limit_attempts"
        indexes = (("scope", "key", "created_at"),)
