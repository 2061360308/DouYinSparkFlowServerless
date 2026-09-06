from __future__ import annotations

from datetime import datetime, timezone
from zoneinfo import ZoneInfo

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel

from server.deps import AuthContext, Services, admin_csrf, get_services, require_admin
from server.schemas import (
    AdminUserQuotaResponse,
    AdminUserRow,
    ListUsersResponse,
    OkResponse,
    QuotaPolicy,
    SystemConfigResponse,
    SystemConfigUpdateBody,
    TemporaryPasswordResponse,
)
from core.services import ValidationError
from core.services.task_capacity import TaskCapacityService
from core.services.users import UserService
from core.db import SystemConfigDB
from core.db.config import SYSTEM_CONFIG_KEYS
from core.db.models import User

router = APIRouter(prefix="/api/admin", tags=["admin"])

PAGE_SIZE = 8
SHANGHAI = ZoneInfo("Asia/Shanghai")


def _parse_dt(value: str, *, required: bool) -> datetime | None:
    clean = (value or "").strip()
    if not clean:
        if required:
            raise ValidationError("请选择开始时间")
        return None
    try:
        parsed = datetime.fromisoformat(clean)
    except ValueError as error:
        raise ValidationError("时间格式无效") from error
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=SHANGHAI)
    # 存 naive-UTC
    return parsed.astimezone(timezone.utc).replace(tzinfo=None)


def _user_dict(user: User) -> dict:
    return {
        "id": user.id,
        "username": user.username,
        "role": user.role,
        "status": user.status,
        "must_change_password": user.must_change_password,
        "created_at": user.created_at.isoformat() if user.created_at else None,
    }


class CreateUserBody(BaseModel):
    username: str


class DeleteUserBody(BaseModel):
    confirmation: str


class QuotaPolicyBody(BaseModel):
    default_amount: int
    default_duration_days: int | None = None
    max_saved_tasks: int


class GrantBody(BaseModel):
    amount: int
    starts_at: str
    expires_at: str = ""
    label: str


class TaskLimitBody(BaseModel):
    task_limit: int


@router.get("/users", response_model=ListUsersResponse)
async def list_users(
    q: str = "",
    page: int = 1,
    ctx: AuthContext = Depends(require_admin),
) -> dict:
    capacity = TaskCapacityService()
    query = User.all()
    keyword = q.strip().lower()
    if keyword:
        query = query.filter(username__contains=keyword)
    total = await query.count()
    pages = max(1, (total + PAGE_SIZE - 1) // PAGE_SIZE)
    current = min(max(1, page), pages)
    users = await query.order_by("created_at", "username").offset(
        (current - 1) * PAGE_SIZE
    ).limit(PAGE_SIZE)
    items = []
    for user in users:
        row = _user_dict(user)
        row["quota"] = await capacity.summary_for(user)
        items.append(row)
    return {
        "items": items,
        "page": {"page": current, "pages": pages, "total": total,
                 "has_previous": current > 1, "has_next": current < pages},
    }


@router.post("/users", response_model=TemporaryPasswordResponse)
async def create_user(
    body: CreateUserBody,
    ctx: AuthContext = Depends(admin_csrf),
    services: Services = Depends(get_services),
) -> dict:
    _user, temporary = await UserService(services.passwords).create(body.username)
    return {"temporary_password": temporary}


@router.post("/users/{user_id}/toggle", response_model=OkResponse)
async def toggle_user(
    user_id: str,
    ctx: AuthContext = Depends(admin_csrf),
    services: Services = Depends(get_services),
) -> dict:
    user = await User.get_or_none(id=user_id)
    if user is None:
        raise HTTPException(404)
    await UserService(services.passwords).set_disabled(
        ctx.user.id, user.id, user.status == "active"
    )
    return {"ok": True}


@router.post("/users/{user_id}/reset-password", response_model=TemporaryPasswordResponse)
async def reset_password(
    user_id: str,
    ctx: AuthContext = Depends(admin_csrf),
    services: Services = Depends(get_services),
) -> dict:
    temporary = await UserService(services.passwords).reset_password(ctx.user.id, user_id)
    return {"temporary_password": temporary}


@router.delete("/users/{user_id}", response_model=OkResponse)
async def delete_user(
    user_id: str,
    body: DeleteUserBody,
    ctx: AuthContext = Depends(admin_csrf),
    services: Services = Depends(get_services),
) -> dict:
    await UserService(services.passwords).delete(ctx.user.id, user_id, body.confirmation)
    return {"ok": True}


@router.get("/quota-policy", response_model=QuotaPolicy)
async def get_quota_policy(ctx: AuthContext = Depends(require_admin)) -> dict:
    policy = await TaskCapacityService().policy()
    return {
        "default_amount": policy.default_amount,
        "default_duration_days": policy.default_duration_days,
        "max_saved_tasks": policy.max_saved_tasks,
    }


@router.put("/quota-policy", response_model=OkResponse)
async def update_quota_policy(
    body: QuotaPolicyBody,
    ctx: AuthContext = Depends(admin_csrf),
) -> dict:
    await TaskCapacityService().update_policy(
        ctx.user.id, body.default_amount, body.default_duration_days, body.max_saved_tasks
    )
    return {"ok": True}


@router.get("/users/{user_id}/quota", response_model=AdminUserQuotaResponse)
async def user_quota(
    user_id: str,
    ctx: AuthContext = Depends(require_admin),
) -> dict:
    target = await User.get_or_none(id=user_id)
    if target is None or target.role == "admin":
        raise HTTPException(404)
    capacity = TaskCapacityService()
    await capacity.reconcile_user(target.id)
    return {"user": _user_dict(target), "quota": await capacity.summary_for(target)}


@router.post("/users/{user_id}/quota-grants", response_model=OkResponse)
async def add_grant(
    user_id: str,
    body: GrantBody,
    ctx: AuthContext = Depends(admin_csrf),
) -> dict:
    await TaskCapacityService().grant(
        ctx.user.id, user_id, body.amount,
        _parse_dt(body.starts_at, required=True),
        _parse_dt(body.expires_at, required=False),
        body.label,
    )
    return {"ok": True}


@router.post("/quota-grants/{grant_id}/revoke", response_model=OkResponse)
async def revoke_grant(
    grant_id: str,
    ctx: AuthContext = Depends(admin_csrf),
) -> dict:
    await TaskCapacityService().revoke(ctx.user.id, grant_id)
    return {"ok": True}


@router.post("/users/{user_id}/task-limit", response_model=OkResponse)
async def set_task_limit(
    user_id: str,
    body: TaskLimitBody,
    ctx: AuthContext = Depends(admin_csrf),
) -> dict:
    await TaskCapacityService().set_limit(ctx.user.id, user_id, body.task_limit)
    return {"ok": True}


@router.get("/system-config", response_model=SystemConfigResponse)
async def get_system_config(ctx: AuthContext = Depends(require_admin)) -> dict:
    """读取所有已注册的系统配置（缺记录时回落默认值）。"""
    return {"values": await SystemConfigDB.get_many()}


@router.put("/system-config", response_model=OkResponse)
async def update_system_config(
    body: SystemConfigUpdateBody,
    ctx: AuthContext = Depends(admin_csrf),
) -> dict:
    """批量更新系统配置（键须在 SYSTEM_CONFIG_KEYS 中注册）。"""
    await SystemConfigDB.set_many(body.values)
    return {"ok": True}
