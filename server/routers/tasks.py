from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel

from server.deps import AuthContext, Services, current_user, get_services, user_csrf
from server.schemas import Availability, ListTasksResponse, OkResponse, TaskItem
from core.services import Conflict, NotFound, ValidationError
from core.services.accounts import AccountService
from core.services.audit import AuditService
from core.services.task_capacity import TaskCapacityService
from core.services.tasks import TaskService
from core.services.task_scheduling import sync_task, schedule_status
from core.db.models import SparkTask, SparkTaskTargetIdentity, User

router = APIRouter(prefix="/api/tasks", tags=["tasks"])


class TaskBody(BaseModel):
    account_id: str
    target_name: str
    target_sec_uid: str = ""
    send_time: str
    message_template: str


def _iso(value) -> str | None:
    return value.isoformat() if value is not None else None


async def _task_dict(task: SparkTask) -> dict:
    binding = await SparkTaskTargetIdentity.get_or_none(task_id=task.id)
    return {
        **await schedule_status(task),
        "id": task.id,
        "account_id": task.douyin_account_id,
        "target_name": task.target_name,
        "target_sec_uid": binding.sec_uid if binding else "",
        "send_time": task.send_time,
        "message_template": task.message_template,
        "enabled": task.enabled,
        "next_run_at": _iso(task.next_run_at),
    }


def _service(services: Services) -> TaskService:
    return TaskService(AccountService(services.cookie_cipher, AuditService()), AuditService())


@router.get("", response_model=ListTasksResponse)
async def list_tasks(
    ctx: AuthContext = Depends(current_user),
    services: Services = Depends(get_services),
) -> dict:
    capacity = TaskCapacityService()
    await capacity.reconcile_user(ctx.user.id)
    service = _service(services)
    tasks = await service.list_owned(ctx.user.id)
    return {
        "items": [await _task_dict(task) for task in tasks],
        "quota": await capacity.summary_for(ctx.user),
    }


@router.get("/availability", response_model=Availability)
async def availability(
    send_time: str,
    exclude_task_id: str = "",
    ctx: AuthContext = Depends(current_user),
) -> dict:
    excluded = exclude_task_id.strip() or None
    if excluded:
        task = await SparkTask.get_or_none(id=excluded)
        if task is None or (ctx.user.role != "admin" and task.owner_user_id != ctx.user.id):
            raise HTTPException(404)
    result = await TaskCapacityService().availability(send_time, excluded)
    return {
        "available": result.available,
        "remaining": result.remaining,
        "suggestions": list(result.suggestions),
    }


@router.post("", response_model=TaskItem)
async def create_task(
    body: TaskBody,
    ctx: AuthContext = Depends(user_csrf),
    services: Services = Depends(get_services),
) -> dict:
    task = await _service(services).create(
        ctx.user.id, body.account_id, body.target_name,
        body.send_time, body.message_template, target_sec_uid=body.target_sec_uid,
    )
    return await _task_dict(task)


@router.get("/{task_id}", response_model=TaskItem)
async def get_task(
    task_id: str,
    ctx: AuthContext = Depends(current_user),
    services: Services = Depends(get_services),
) -> dict:
    task = await _service(services).get_owned(ctx.user.id, task_id)
    return await _task_dict(task)


@router.put("/{task_id}", response_model=TaskItem)
async def update_task(
    task_id: str,
    body: TaskBody,
    ctx: AuthContext = Depends(user_csrf),
    services: Services = Depends(get_services),
) -> dict:
    task = await _service(services).update_owned(
        ctx.user.id, task_id, body.account_id, body.target_name,
        body.send_time, body.message_template, target_sec_uid=body.target_sec_uid,
    )
    return await _task_dict(task)


@router.post("/{task_id}/toggle", response_model=TaskItem)
async def toggle_task(
    task_id: str,
    ctx: AuthContext = Depends(user_csrf),
    services: Services = Depends(get_services),
) -> dict:
    service = _service(services)
    task = await service.get_owned(ctx.user.id, task_id)
    task = await service.set_enabled_owned(ctx.user.id, task_id, not task.enabled)
    return await _task_dict(task)


@router.delete("/{task_id}", response_model=OkResponse)
async def delete_task(
    task_id: str,
    ctx: AuthContext = Depends(user_csrf),
    services: Services = Depends(get_services),
) -> dict:
    await _service(services).delete_owned(ctx.user.id, task_id)
    return {"ok": True}


@router.post('/{task_id}/sync', response_model=TaskItem)
async def retry_schedule(task_id: str, ctx: AuthContext = Depends(user_csrf), services: Services = Depends(get_services)):
    task = await _service(services).get_owned(ctx.user.id, task_id)
    await sync_task(task.id)
    await task.refresh_from_db()
    return await _task_dict(task)
