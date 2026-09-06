"""内部机器接口 /api/internal/*：仅服务令牌可访问（供续火任务函数调用）。

任务函数(FC 事件函数 / 本地 core.task.run)通过服务令牌访问这些接口：
取计划任务/续火任务详情与解密 cookie、申请远程浏览器、回写执行状态与执行记录。
DB 只在本层(server)读写；任务函数不直连数据库。
"""

from __future__ import annotations

from datetime import datetime, timezone

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel

from server.deps import Services, get_services, require_service
from server.schemas import (
    AccountCookiesResponse,
    BrowserAcquireResponse,
    OkResponse,
    ScheduledTaskDetail,
    TaskItem,
    WriteRunResponse,
)
from core.task.crud import ScheduledTaskDB
from core.timeutil import utcnow
from core.db.models import (
    DouyinAccount,
    SparkTask,
    SparkTaskTargetIdentity,
    TaskRun,
)

router = APIRouter(prefix="/api/internal", tags=["internal"], dependencies=[Depends(require_service)])


class ResultBody(BaseModel):
    ok: bool


class AcquireBody(BaseModel):
    sessionid: str
    fingerprint: dict = {}


class RunBody(BaseModel):
    status: str
    stage: str = ""
    error_code: str | None = None
    error_summary: str | None = None
    scheduled_for: str | None = None


def _iso(value) -> str | None:
    return value.isoformat() if value is not None else None


# ---- 计划任务(通用调度层) ----
@router.get("/scheduled-tasks/{task_id}", response_model=ScheduledTaskDetail)
async def get_scheduled_task(task_id: str) -> dict:
    task = await ScheduledTaskDB.get(task_id)
    if task is None:
        raise HTTPException(404, "scheduled task not found")
    return task


@router.post("/scheduled-tasks/{task_id}/started", response_model=OkResponse)
async def scheduled_task_started(task_id: str) -> dict:
    resp = await ScheduledTaskDB.mark_started(task_id)
    if not resp["ok"]:
        raise HTTPException(404, resp["msg"])
    return {"ok": True}


@router.post("/scheduled-tasks/{task_id}/result", response_model=OkResponse)
async def scheduled_task_result(task_id: str, body: ResultBody) -> dict:
    resp = await ScheduledTaskDB.mark_result(task_id, ok=body.ok)
    if not resp["ok"]:
        raise HTTPException(404, resp["msg"])
    return {"ok": True}


# ---- 续火业务任务 ----
@router.get("/spark-tasks/{spark_task_id}", response_model=TaskItem)
async def get_spark_task(spark_task_id: str) -> dict:
    task = await SparkTask.get_or_none(id=spark_task_id)
    if task is None:
        raise HTTPException(404, "spark task not found")
    binding = await SparkTaskTargetIdentity.get_or_none(task_id=task.id)
    return {
        "id": task.id,
        "owner_user_id": task.owner_user_id,
        "account_id": task.douyin_account_id,
        "target_name": task.target_name,
        "target_sec_uid": binding.sec_uid if binding else "",
        "send_time": task.send_time,
        "message_template": task.message_template,
        "enabled": task.enabled,
    }


@router.get("/accounts/{account_id}/cookies", response_model=AccountCookiesResponse)
async def get_account_cookies(
    account_id: str,
    services: Services = Depends(get_services),
) -> dict:
    account = await DouyinAccount.get_or_none(id=account_id)
    if account is None:
        raise HTTPException(404, "account not found")
    try:
        raw = services.cookie_cipher.decrypt(account.encrypted_cookies, account.cookie_nonce)
    except Exception as error:  # noqa: BLE001
        raise HTTPException(500, f"decrypt failed: {error}") from error
    return {
        "account_id": account.id,
        "cookie_version": account.cookie_version,
        "cookies_json": raw.decode("utf-8", errors="replace"),
    }


@router.post("/spark-tasks/{spark_task_id}/runs", response_model=WriteRunResponse)
async def write_run(spark_task_id: str, body: RunBody) -> dict:
    task = await SparkTask.get_or_none(id=spark_task_id)
    if task is None:
        raise HTTPException(404, "spark task not found")
    scheduled_for = utcnow()
    if body.scheduled_for:
        try:
            parsed = datetime.fromisoformat(body.scheduled_for)
            scheduled_for = parsed.astimezone(timezone.utc).replace(tzinfo=None) if parsed.tzinfo else parsed
        except ValueError:
            pass
    finished = body.status in {"success", "failed", "skipped"}
    run = await TaskRun.create(
        task_id=task.id,
        scheduled_for=scheduled_for,
        status=body.status,
        stage=body.stage or body.status,
        started_at=utcnow(),
        finished_at=utcnow() if finished else None,
        error_code=body.error_code,
        error_summary=(body.error_summary or None) and body.error_summary[:240],
    )
    return {"id": run.id}


# ---- 远程浏览器申请(经 BrowserManager, 集中并发计数) ----
@router.post("/browser/acquire", response_model=BrowserAcquireResponse)
async def acquire_browser(body: AcquireBody) -> dict:
    from core.browser import BrowserManager

    mgr = await BrowserManager.get_instance()
    res = await mgr.acquire(body.sessionid, **(body.fingerprint or {}))
    if not res.get("ok"):
        raise HTTPException(409, res.get("msg", "acquire failed"))
    return {
        "sessionid": res.get("sessionid"),
        "ws_url": res.get("ws_url"),
        "headers": res.get("headers") or {},
        "mode": res.get("mode"),
    }
