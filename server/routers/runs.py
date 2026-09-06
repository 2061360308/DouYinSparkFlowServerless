from __future__ import annotations

from fastapi import APIRouter, Depends

from server.deps import AuthContext, current_user
from server.schemas import ListRunsResponse
from core.db.models import TaskRun, User

router = APIRouter(prefix="/api/runs", tags=["runs"])

PAGE_SIZE = 6


def _iso(value) -> str | None:
    return value.isoformat() if value is not None else None


@router.get("", response_model=ListRunsResponse)
async def list_runs(
    page: int = 1,
    ctx: AuthContext = Depends(current_user),
) -> dict:
    is_admin = ctx.user.role == "admin"
    query = TaskRun.all().select_related("task")
    if not is_admin:
        query = query.filter(task__owner_user_id=ctx.user.id)

    total = await query.count()
    pages = max(1, (total + PAGE_SIZE - 1) // PAGE_SIZE)
    current = min(max(1, page), pages)
    runs = (
        await query.order_by("-scheduled_for")
        .offset((current - 1) * PAGE_SIZE)
        .limit(PAGE_SIZE)
    )

    owner_names: dict[str, str] = {}
    if is_admin:
        owner_ids = {run.task.owner_user_id for run in runs if run.task}
        if owner_ids:
            for user in await User.filter(id__in=list(owner_ids)):
                owner_names[user.id] = user.username

    items = []
    for run in runs:
        task = run.task
        row = {
            "id": run.id,
            "task_id": run.task_id,
            "target_name": task.target_name if task else None,
            "send_time": task.send_time if task else None,
            "scheduled_for": _iso(run.scheduled_for),
            "status": run.status,
            "stage": run.stage,
            "started_at": _iso(run.started_at),
            "finished_at": _iso(run.finished_at),
            "error_code": run.error_code,
            "error_summary": run.error_summary,
        }
        if is_admin and task:
            row["owner_username"] = owner_names.get(task.owner_user_id)
        items.append(row)

    return {
        "items": items,
        "page": {
            "page": current,
            "pages": pages,
            "total": total,
            "has_previous": current > 1,
            "has_next": current < pages,
        },
        "show_owner": is_admin,
    }
