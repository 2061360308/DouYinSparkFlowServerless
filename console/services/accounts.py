"""抖音账号服务（异步）。由 spark_console.services.accounts 迁移。

本期不含浏览器登录写入（create_from_storage_state 属执行面，暂不迁）；保留
手动按 cookie JSON 添加、查询、改名、删除，及供执行面使用的解密方法。
"""

from __future__ import annotations

import json

from db.console_models import DouyinAccount, SparkTask
from console.crypto import CookieCipher
from console.services import NotFound, ValidationError
from console.services.audit import AuditService


class AccountService:
    def __init__(self, cipher: CookieCipher, audit: AuditService | None = None):
        self.cipher = cipher
        self.audit = audit or AuditService()

    async def create(self, owner_id: str, display_name: str, cookies: bytes | str) -> DouyinAccount:
        name = self._validated_display_name(display_name)
        raw = cookies.encode("utf-8") if isinstance(cookies, str) else cookies
        try:
            parsed = json.loads(raw)
        except (ValueError, UnicodeDecodeError) as error:
            raise ValidationError("Cookie 必须是有效的 JSON") from error
        if not isinstance(parsed, list) or not parsed:
            raise ValidationError("Cookie JSON 必须是非空数组")
        sealed = self.cipher.encrypt(raw)
        account = await DouyinAccount.create(
            owner_user_id=owner_id,
            display_name=name,
            encrypted_cookies=sealed.ciphertext,
            cookie_nonce=sealed.nonce,
        )
        await self.audit.write(owner_id, "account.created", "douyin_account", account.id)
        return account

    async def rename_owned(self, owner_id: str, account_id: str, display_name: str) -> DouyinAccount:
        account = await self.get_owned(owner_id, account_id)
        account.display_name = self._validated_display_name(display_name)
        await account.save(update_fields=["display_name", "updated_at"])
        await self.audit.write(owner_id, "account.renamed", "douyin_account", account.id)
        return account

    async def get_owned(self, owner_id: str, account_id: str) -> DouyinAccount:
        account = await DouyinAccount.get_or_none(id=account_id, owner_user_id=owner_id)
        if account is None:
            raise NotFound("account not found")
        return account

    async def list_owned(self, owner_id: str) -> list[dict[str, str]]:
        accounts = await DouyinAccount.filter(owner_user_id=owner_id).order_by("created_at")
        return [
            {
                "id": item.id,
                "display_name": item.display_name,
                "validation_state": item.validation_state,
            }
            for item in accounts
        ]

    async def decrypt_for_worker(self, account_id: str) -> bytearray:
        account = await DouyinAccount.get_or_none(id=account_id)
        if account is None:
            raise NotFound("account not found")
        return bytearray(self.cipher.decrypt(account.encrypted_cookies, account.cookie_nonce))

    async def delete_owned(self, owner_id: str, account_id: str) -> None:
        account = await self.get_owned(owner_id, account_id)
        # 解绑其关联任务并停用
        await SparkTask.filter(douyin_account_id=account.id).update(
            enabled=False, douyin_account_id=None
        )
        await account.delete()
        await self.audit.write(owner_id, "account.deleted", "douyin_account", account_id)

    @staticmethod
    def _validated_display_name(display_name: str) -> str:
        name = display_name.strip()
        if not name or len(name) > 64:
            raise ValidationError("账号名称须为 1–64 个字符")
        return name
