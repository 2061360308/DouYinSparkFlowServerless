"""抖音账号及联系人相关模型。"""

from __future__ import annotations

from tortoise import fields, models

from .base import uuid_string


class DouyinAccount(models.Model):
    id = fields.CharField(max_length=36, primary_key=True, default=uuid_string)
    owner_user = fields.ForeignKeyField(
        "models.User", related_name="douyin_accounts",
        on_delete=fields.CASCADE, db_index=True,
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


class DouyinAccountIdentity(models.Model):
    account = fields.OneToOneField(
        "models.DouyinAccount", related_name="identity",
        on_delete=fields.CASCADE, primary_key=True,
    )
    douyin_unique_id = fields.CharField(max_length=64, null=True)
    created_at = fields.DatetimeField(auto_now_add=True)

    class Meta:
        table = "douyin_account_identities"


class DouyinConversation(models.Model):
    # 原复合主键 (account_id, display_name) → 代理主键 + unique_together
    id = fields.IntField(primary_key=True)
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
    id = fields.IntField(primary_key=True)
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
