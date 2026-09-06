"""用户与认证相关模型。"""

from __future__ import annotations

from enum import StrEnum

from tortoise import fields, models

from .base import uuid_string


class User(models.Model):
    id = fields.CharField(max_length=36, primary_key=True, default=uuid_string)
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


class WebSession(models.Model):
    id = fields.CharField(max_length=36, primary_key=True, default=uuid_string)
    user = fields.ForeignKeyField(
        "models.User", related_name="web_sessions",
        on_delete=fields.CASCADE, db_index=True,
    )
    token_hash = fields.CharField(max_length=64, unique=True)
    csrf_token = fields.CharField(max_length=64)
    expires_at = fields.DatetimeField()
    created_at = fields.DatetimeField(auto_now_add=True)

    class Meta:
        table = "web_sessions"


class PendingRegistration(models.Model):
    id = fields.CharField(max_length=36, primary_key=True, default=uuid_string)
    username = fields.CharField(max_length=32, db_index=True)
    password_hash = fields.TextField()
    invite = fields.ForeignKeyField(
        "models.InviteCode", related_name="pending_registrations",
        on_delete=fields.CASCADE, db_index=True,
    )
    email_ciphertext = fields.BinaryField()
    email_nonce = fields.BinaryField()
    email_lookup_hash = fields.CharField(max_length=64, db_index=True)
    code_hash = fields.CharField(max_length=64)
    failed_attempts = fields.IntField(default=0)
    send_count = fields.IntField(default=1)
    client_key_hash = fields.CharField(max_length=64)
    code_expires_at = fields.DatetimeField()
    resend_available_at = fields.DatetimeField()
    expires_at = fields.DatetimeField(db_index=True)
    created_at = fields.DatetimeField(auto_now_add=True)
    updated_at = fields.DatetimeField(auto_now=True)

    class Meta:
        table = "pending_registrations"


class EmailVerificationRequest(models.Model):
    id = fields.CharField(max_length=36, primary_key=True, default=uuid_string)
    user = fields.ForeignKeyField(
        "models.User", related_name="email_verifications",
        on_delete=fields.CASCADE, db_index=True,
    )
    purpose = fields.CharField(max_length=24)
    email_ciphertext = fields.BinaryField()
    email_nonce = fields.BinaryField()
    email_lookup_hash = fields.CharField(max_length=64, db_index=True)
    code_hash = fields.CharField(max_length=64)
    failed_attempts = fields.IntField(default=0)
    send_count = fields.IntField(default=1)
    code_expires_at = fields.DatetimeField()
    resend_available_at = fields.DatetimeField()
    expires_at = fields.DatetimeField(db_index=True)
    consumed_at = fields.DatetimeField(null=True)
    created_at = fields.DatetimeField(auto_now_add=True)

    class Meta:
        table = "email_verification_requests"
