from __future__ import annotations

from fastapi import APIRouter, Depends
from pydantic import BaseModel

from server.deps import AuthContext, Services, current_user, get_services, user_csrf
from server.schemas import (
    CreateAccountResponse,
    ListAccountsResponse,
    ListConversationsResponse,
    OkResponse,
)
from core.services.accounts import AccountService
from core.services.audit import AuditService
from core.db.models import DouyinContactIdentity, DouyinConversation

router = APIRouter(prefix="/api/accounts", tags=["accounts"])


class CreateAccountBody(BaseModel):
    display_name: str
    cookies: str


@router.get("", response_model=ListAccountsResponse)
async def list_accounts(
    ctx: AuthContext = Depends(current_user),
    services: Services = Depends(get_services),
) -> dict:
    service = AccountService(services.cookie_cipher)
    return {"items": await service.list_owned(ctx.user.id)}


@router.post("", response_model=CreateAccountResponse)
async def create_account(
    body: CreateAccountBody,
    ctx: AuthContext = Depends(user_csrf),
    services: Services = Depends(get_services),
) -> dict:
    service = AccountService(services.cookie_cipher, AuditService())
    account = await service.create(ctx.user.id, body.display_name, body.cookies)
    return {"id": account.id, "display_name": account.display_name}


@router.delete("/{account_id}", response_model=OkResponse)
async def delete_account(
    account_id: str,
    ctx: AuthContext = Depends(user_csrf),
    services: Services = Depends(get_services),
) -> dict:
    service = AccountService(services.cookie_cipher, AuditService())
    await service.delete_owned(ctx.user.id, account_id)
    return {"ok": True}


@router.get("/{account_id}/conversations", response_model=ListConversationsResponse)
async def account_conversations(
    account_id: str,
    ctx: AuthContext = Depends(current_user),
    services: Services = Depends(get_services),
) -> dict:
    # 确认归属
    await AccountService(services.cookie_cipher).get_owned(ctx.user.id, account_id)
    contacts = await DouyinContactIdentity.filter(account_id=account_id)
    aliases = {
        value
        for contact in contacts
        for value in (contact.remark_name, contact.nickname, contact.unique_id, contact.short_id)
        if value
    }
    items = [
        {
            "name": contact.remark_name or contact.nickname or contact.unique_id or contact.short_id,
            "sec_uid": contact.sec_uid,
        }
        for contact in contacts
        if (contact.remark_name or contact.nickname or contact.unique_id or contact.short_id)
    ]
    names = await DouyinConversation.filter(account_id=account_id).values_list(
        "display_name", flat=True
    )
    items.extend({"name": name, "sec_uid": None} for name in names if name not in aliases)
    return {"items": sorted(items, key=lambda item: item["name"])}
