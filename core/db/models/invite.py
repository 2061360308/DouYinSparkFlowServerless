"""邀请码相关模型。"""

from __future__ import annotations

from tortoise import fields, models

from .base import uuid_string


class InviteCode(models.Model):
    id = fields.CharField(max_length=36, primary_key=True, default=uuid_string)
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
        on_delete=fields.CASCADE, primary_key=True,
    )
    ciphertext = fields.BinaryField()
    nonce = fields.BinaryField()

    class Meta:
        table = "invite_code_secrets"
