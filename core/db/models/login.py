"""抖音扫码登录相关模型。"""

from __future__ import annotations

from enum import StrEnum

from tortoise import fields, models

from .base import uuid_string


class ScanStatus(StrEnum):
    QUEUED = "queued"
    LOADING_QR = "loading_qr"
    AWAITING_SCAN = "awaiting_scan"
    CONFIRMING = "confirming"
    SUCCEEDED = "succeeded"
    FAILED = "failed"
    EXPIRED = "expired"
    CANCELLED = "cancelled"


class DouyinLoginSession(models.Model):
    id = fields.CharField(max_length=36, primary_key=True, default=uuid_string)
    owner_user = fields.ForeignKeyField(
        "models.User", related_name="login_sessions",
        on_delete=fields.CASCADE, db_index=True,
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
    id = fields.IntField(primary_key=True)
    scan = fields.ForeignKeyField(
        "models.DouyinLoginSession", related_name="actions",
        on_delete=fields.CASCADE, db_index=True,
    )
    kind = fields.CharField(max_length=16)
    x_million = fields.IntField()
    y_million = fields.IntField()
    created_at = fields.DatetimeField(auto_now_add=True)
    consumed_at = fields.DatetimeField(null=True)

    class Meta:
        table = "douyin_login_actions"


class DouyinLoginInput(models.Model):
    id = fields.IntField(primary_key=True)
    scan = fields.ForeignKeyField(
        "models.DouyinLoginSession", related_name="inputs",
        on_delete=fields.CASCADE, db_index=True,
    )
    ciphertext = fields.BinaryField(null=True)
    nonce = fields.BinaryField(null=True)
    created_at = fields.DatetimeField(auto_now_add=True)
    consumed_at = fields.DatetimeField(null=True)

    class Meta:
        table = "douyin_login_inputs"
