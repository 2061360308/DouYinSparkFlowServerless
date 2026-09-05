"""``scheduled_tasks`` 表读写（全部为静态方法，``@with_db`` 自动管理连接）。

对外返回统一结构 ``{"ok", "code", "detail", "msg"}``（与 db 包其它读写类一致）。
cron 按 Asia/Shanghai 解释，``next_run_at`` 计算后以 naive-UTC 落库。
"""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Any, Optional
from zoneinfo import ZoneInfo

from db.connection import with_db

from . import cron_utils
from .models import ScheduledTask

# 状态码
OK = 0
ERR_INVALID_CRON = 2001
ERR_TASK_NOT_FOUND = 2002

OK_MSG = "操作成功"

_SH = ZoneInfo("Asia/Shanghai")

# 区分「更新时未传该字段」与「显式置为 None」
_UNSET: Any = object()


def _resp(ok: bool, code: int, detail: Optional[dict] = None, msg: str = OK_MSG) -> dict:
    return {"ok": ok, "code": code, "detail": detail, "msg": msg}


def _iso(value: Optional[datetime]) -> Optional[str]:
    return value.isoformat() if value is not None else None


def _row_to_dict(row: ScheduledTask) -> dict:
    return {
        "task_id": row.task_id,
        "cron_expr": row.cron_expr,
        "event_category": row.event_category,
        "params": row.params,
        "target_env": row.target_env,
        "enabled": row.enabled,
        "status": row.status,
        "last_run_at": _iso(row.last_run_at),
        "next_run_at": _iso(row.next_run_at),
        "created_at": _iso(row.created_at),
        "updated_at": _iso(row.updated_at),
    }


def _utc_now_naive() -> datetime:
    return datetime.now(timezone.utc).replace(tzinfo=None)


def compute_next_run(cron_expr: str, after_utc: Optional[datetime] = None) -> datetime:
    """按 Asia/Shanghai 解释 cron，返回严格晚于 ``after_utc`` 的下次执行时刻（naive-UTC）。"""
    after_utc = after_utc or _utc_now_naive()
    after_sh = after_utc.replace(tzinfo=timezone.utc).astimezone(_SH).replace(tzinfo=None)
    next_sh = cron_utils.next_after(cron_expr, after_sh)
    return next_sh.replace(tzinfo=_SH).astimezone(timezone.utc).replace(tzinfo=None)


class ScheduledTaskDB:
    """计划任务表读写类。"""

    @staticmethod
    @with_db
    async def create(
        event_category: str,
        cron_expr: str,
        *,
        params: Optional[Any] = None,
        target_env: str = "linux",
        enabled: bool = True,
        task_id: Optional[str] = None,
    ) -> dict:
        """创建计划任务；cron 非法则返回失败码，不落库。"""
        try:
            cron_utils.validate(cron_expr)
        except cron_utils.CronError as error:
            return _resp(False, ERR_INVALID_CRON, msg=f"cron 非法：{error}")
        next_run = compute_next_run(cron_expr) if enabled else None
        create_kwargs: dict[str, Any] = dict(
            cron_expr=cron_expr,
            event_category=event_category,
            params=params,
            target_env=target_env,
            enabled=enabled,
            next_run_at=next_run,
        )
        if task_id is not None:
            create_kwargs["task_id"] = task_id
        row = await ScheduledTask.create(**create_kwargs)
        return _resp(True, OK, detail=_row_to_dict(row))

    @staticmethod
    @with_db
    async def get(task_id: str) -> Optional[dict]:
        """按 task_id 查任务；不存在返回 None。"""
        row = await ScheduledTask.get_or_none(task_id=task_id)
        return _row_to_dict(row) if row is not None else None

    @staticmethod
    @with_db
    async def list_all() -> list[dict]:
        """列出全部任务。"""
        return [_row_to_dict(r) for r in await ScheduledTask.all()]

    @staticmethod
    @with_db
    async def list_enabled() -> list[dict]:
        """列出启用中的任务（供调度器全量对账）。"""
        return [_row_to_dict(r) for r in await ScheduledTask.filter(enabled=True)]

    @staticmethod
    @with_db
    async def update(
        task_id: str,
        *,
        cron_expr: Optional[str] = None,
        event_category: Optional[str] = None,
        params: Any = _UNSET,
        target_env: Optional[str] = None,
    ) -> dict:
        """更新任务；仅改传入字段。cron 变更时重算 next_run_at。"""
        row = await ScheduledTask.get_or_none(task_id=task_id)
        if row is None:
            return _resp(False, ERR_TASK_NOT_FOUND, msg="task 不存在")
        fields: list[str] = []
        if cron_expr is not None:
            try:
                cron_utils.validate(cron_expr)
            except cron_utils.CronError as error:
                return _resp(False, ERR_INVALID_CRON, msg=f"cron 非法：{error}")
            row.cron_expr = cron_expr
            fields.append("cron_expr")
            if row.enabled:
                row.next_run_at = compute_next_run(cron_expr)
                fields.append("next_run_at")
        if event_category is not None:
            row.event_category = event_category
            fields.append("event_category")
        if params is not _UNSET:
            row.params = params
            fields.append("params")
        if target_env is not None:
            row.target_env = target_env
            fields.append("target_env")
        if fields:
            await row.save(update_fields=[*fields, "updated_at"])
        return _resp(True, OK, detail=_row_to_dict(row))

    @staticmethod
    @with_db
    async def set_enabled(task_id: str, enabled: bool) -> dict:
        """启用/禁用任务；启用时重算 next_run_at，禁用时清空。"""
        row = await ScheduledTask.get_or_none(task_id=task_id)
        if row is None:
            return _resp(False, ERR_TASK_NOT_FOUND, msg="task 不存在")
        row.enabled = enabled
        row.next_run_at = compute_next_run(row.cron_expr) if enabled else None
        await row.save(update_fields=["enabled", "next_run_at", "updated_at"])
        return _resp(True, OK, detail=_row_to_dict(row))

    @staticmethod
    @with_db
    async def delete(task_id: str) -> dict:
        """删除任务（幂等）。"""
        await ScheduledTask.filter(task_id=task_id).delete()
        return _resp(True, OK, msg="删除成功")

    @staticmethod
    @with_db
    async def mark_started(task_id: str) -> dict:
        """标记任务开始执行（status=running）。"""
        row = await ScheduledTask.get_or_none(task_id=task_id)
        if row is None:
            return _resp(False, ERR_TASK_NOT_FOUND, msg="task 不存在")
        row.status = "running"
        await row.save(update_fields=["status", "updated_at"])
        return _resp(True, OK, detail=_row_to_dict(row))

    @staticmethod
    @with_db
    async def mark_result(task_id: str, ok: bool) -> dict:
        """回写执行结果：status、last_run_at=now，并重算 next_run_at。"""
        row = await ScheduledTask.get_or_none(task_id=task_id)
        if row is None:
            return _resp(False, ERR_TASK_NOT_FOUND, msg="task 不存在")
        now = _utc_now_naive()
        row.status = "success" if ok else "failed"
        row.last_run_at = now
        if row.enabled:
            row.next_run_at = compute_next_run(row.cron_expr, now)
        await row.save(update_fields=["status", "last_run_at", "next_run_at", "updated_at"])
        return _resp(True, OK, detail=_row_to_dict(row))
