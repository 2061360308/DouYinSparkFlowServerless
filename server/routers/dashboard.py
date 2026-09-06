from __future__ import annotations

from datetime import datetime, timezone

from fastapi import APIRouter, Depends

from server.deps import AuthContext, Services, current_user, get_services
from server.schemas import DashboardData, PlatformStatus
from core.services.accounts import AccountService
from core.services.task_capacity import TaskCapacityService
from core.db.models import SparkTask, TaskRun

router = APIRouter(tags=["dashboard"])

_STATUS_KEYS = ("success", "running", "queued", "failed", "skipped")


def _iso(value) -> str | None:
    return value.isoformat() if value is not None else None


async def _platform_status(user_id: str, is_admin: bool) -> dict:
    runs = TaskRun.all() if is_admin else TaskRun.filter(task__owner_user_id=user_id)
    counts = {key: 0 for key in _STATUS_KEYS}
    total = 0
    for run in await runs.only("status"):
        total += 1
        if run.status in counts:
            counts[run.status] += 1
    return {
        "total": total,
        "success": counts["success"],
        "running": counts["running"],
        "pending": counts["queued"],
        "failed": counts["failed"],
        "worker_online": False,  # 执行面本期未部署
        "updated_at": datetime.now(timezone.utc).isoformat(),
    }


@router.get("/api/platform-status", response_model=PlatformStatus)
async def platform_status(ctx: AuthContext = Depends(current_user)) -> dict:
    await TaskCapacityService().reconcile_user(ctx.user.id)
    return await _platform_status(ctx.user.id, ctx.user.role == "admin")


@router.get("/api/dashboard", response_model=DashboardData)
async def dashboard(
    ctx: AuthContext = Depends(current_user),
    services: Services = Depends(get_services),
) -> dict:
    await TaskCapacityService().reconcile_user(ctx.user.id)
    tasks = await SparkTask.filter(owner_user_id=ctx.user.id).order_by("send_time", "created_at")
    accounts = await AccountService(services.cookie_cipher).list_owned(ctx.user.id)
    recent = (
        await TaskRun.filter(task__owner_user_id=ctx.user.id)
        .select_related("task")
        .order_by("-scheduled_for")
        .limit(5)
    )
    return {
        "tasks": [
            {
                "id": t.id,
                "target_name": t.target_name,
                "send_time": t.send_time,
                "enabled": t.enabled,
                "next_run_at": _iso(t.next_run_at),
            }
            for t in tasks
        ],
        "accounts": accounts,
        "recent_runs": [
            {
                "id": r.id,
                "target_name": r.task.target_name if r.task else None,
                "scheduled_for": _iso(r.scheduled_for),
                "status": r.status,
                "stage": r.stage,
            }
            for r in recent
        ],
        "platform_status": await _platform_status(ctx.user.id, ctx.user.role == "admin"),
    }
