"""内部机器接口 /api/internal/*：仅服务令牌可访问（供续火任务函数调用）。

任务函数(FC 事件函数 / 本地 core.task.run)通过服务令牌访问这些接口：
取计划任务/续火任务详情与解密 cookie、申请远程浏览器、回写执行状态与执行记录。
DB 只在本层(server)读写；任务函数不直连数据库。
"""

from __future__ import annotations
from datetime import datetime
from typing import Literal
from tortoise.exceptions import IntegrityError

from fastapi import APIRouter, Depends, HTTPException, Header
from pydantic import BaseModel, Field
from core.services import executions

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
from core.db.models import (
    DouyinAccount,
    SparkTask,
    SparkTaskTargetIdentity,
)

router = APIRouter(prefix="/api/internal", tags=["internal"], dependencies=[Depends(require_service)])


@router.post('/schedules/reconcile')
async def reconcile_schedules():
    from core.services.task_scheduling import reconcile
    return await reconcile(limit=10)


class ResultBody(BaseModel):
    ok: bool


class ClaimBody(BaseModel):
    scheduled_for: str | None = Field(default=None, max_length=64)


class ExecutionBody(BaseModel):
    token: str = Field(min_length=32, max_length=128)


class FinishBody(ExecutionBody):
    status: str = Field(max_length=16)
    reason: str = Field(default='', max_length=240)


class SendingBody(ExecutionBody):
    message_digest: str = Field(min_length=64, max_length=64)


class ReceiptBody(ExecutionBody):
    source: Literal['douyin_verified_adapter_v1']
    level: Literal['accepted', 'delivered', 'read']
    recipient_uid: str = Field(min_length=1, max_length=256)
    message_digest: str = Field(min_length=64, max_length=64)
    message_id: str = Field(min_length=1, max_length=256, pattern=r'^\S+$')
    conversation_id: str = Field(min_length=1, max_length=256, pattern=r'^\S+$')
    observed_at: datetime


@router.post('/executions/{run_id}/receipt')
async def record_execution_receipt(run_id: str, body: ReceiptBody):
    try:
        return await executions.record_receipt(run_id, body.token, body.model_dump(exclude={'token'}))
    except IntegrityError:
        raise HTTPException(409, '此服务端消息已绑定其他执行') from None


@router.post('/scheduled-tasks/{task_id}/claim')
async def claim_execution(task_id: str, body: ClaimBody):
    return await executions.claim(task_id, body.scheduled_for)


@router.post('/executions/{run_id}/sending')
async def begin_send(run_id: str, body: SendingBody):
    return await executions.begin_send(run_id, body.token, body.message_digest)


@router.post('/executions/{run_id}/finish')
async def finish_execution(run_id: str, body: FinishBody):
    return await executions.finish(run_id, body.token, body.status, body.reason)


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
async def get_scheduled_task(task_id: str, x_spark_execution_protocol: str = Header(default='')) -> dict:
    task = await ScheduledTaskDB.get(task_id)
    if task is None:
        raise HTTPException(404, "scheduled task not found")
    if task['event_category'] == 'douyin_spark':
        if x_spark_execution_protocol != '3':
            raise HTTPException(409, '请更新任务执行器镜像：需要执行协议 v2')
        from core.services.task_scheduling import schedule_status
        spark = await SparkTask.get_or_none(id=(task.get('params') or {}).get('spark_task_id'))
        if not spark or not spark.enabled or not spark.douyin_account_id:
            task['enabled'] = False
        elif (await schedule_status(spark))['schedule_state'] != 'synced':
            task['enabled'] = False
        else:
            owner = await spark.owner_user
            if owner.status != 'active':
                task['enabled'] = False
    return task


@router.post("/scheduled-tasks/{task_id}/started", response_model=OkResponse)
async def scheduled_task_started(task_id: str) -> dict:
    if ((await ScheduledTaskDB.get(task_id)) or {}).get('event_category') == 'douyin_spark':
        raise HTTPException(409, '续火任务必须使用执行领取接口')
    resp = await ScheduledTaskDB.mark_started(task_id)
    if not resp["ok"]:
        raise HTTPException(404, resp["msg"])
    return {"ok": True}


@router.post("/scheduled-tasks/{task_id}/result", response_model=OkResponse)
async def scheduled_task_result(task_id: str, body: ResultBody) -> dict:
    if ((await ScheduledTaskDB.get(task_id)) or {}).get('event_category') == 'douyin_spark':
        raise HTTPException(409, '续火任务必须使用带执行令牌的结果接口')
    resp = await ScheduledTaskDB.mark_result(task_id, ok=body.ok)
    if not resp["ok"]:
        raise HTTPException(404, resp["msg"])
    return {"ok": True}


# ---- 续火业务任务 ----
@router.get("/spark-tasks/{spark_task_id}", response_model=TaskItem)
async def get_spark_task(spark_task_id: str, x_spark_execution_protocol: str = Header(default='')) -> dict:
    if x_spark_execution_protocol != '3':
        raise HTTPException(409, '请更新任务执行器镜像：需要执行协议 v2')
    task = await SparkTask.get_or_none(id=spark_task_id)
    if task is None:
        raise HTTPException(404, "spark task not found")
    if not task.enabled:
        raise HTTPException(409, 'task is paused')
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
    raise HTTPException(410, '旧执行记录写入接口已停用，请更新执行器并使用 claim/sending/finish')


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
