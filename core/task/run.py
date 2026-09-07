"""执行入口：被触发器唤醒后凭 task_id 执行计划任务（统一经 FastAPI 内部接口取数）。

本地：``python -m core.task.run --task-id <task_id>``
FC：容器 invoke server 从事件载荷取 ``task_id`` 后调用 ``run_task``。

流程：经 API 取计划任务 → 读 event_category → registry 路由 handler → 执行
     → 经 API 回写 status（started/result）。执行侧不直连数据库。
"""

from __future__ import annotations

import argparse
import asyncio
import logging

import core.handlers as _handlers  # noqa: F401  触发业务 handler 注册
from core.api_client import ApiClientError, get_client

from . import registry

logger = logging.getLogger(__name__)


async def run_task(task_id: str, scheduled_for: str | None = None) -> dict:
    """执行一个计划任务；返回统一结构 ``{"ok","code","detail","msg"}``。"""
    try:
        client = get_client()
        task = await client.get_scheduled_task(task_id)
    except ApiClientError as error:
        logger.error("取任务失败 task_id=%s: %s", task_id, error)
        return {"ok": False, "code": 2002, "detail": None, "msg": f"取任务失败：{error}", 'retryable': error.status not in {400, 404, 409, 422}}

    if not task.get("enabled", False):
        logger.warning("task 已禁用，跳过执行：%s", task_id)
        return {"ok": False, "code": 2003, "detail": task, "msg": "task 已禁用", 'retryable': False}

    category = task["event_category"]
    try:
        task_handler = registry.get(category)
    except registry.UnknownEventCategory:
        logger.error("未注册的 event_category：%s (task_id=%s)", category, task_id)
        await _safe_result(client, task_id, ok=False)
        return {"ok": False, "code": 2004, "detail": task,
                "msg": f"未注册的 event_category：{category}"}

    execution = None
    if category == 'douyin_spark':
        try:
            execution = await client.claim_execution(task_id, scheduled_for)
        except ApiClientError as error:
            return {'ok': False, 'code': 2006, 'msg': '未取得执行权，不发送', 'retryable': error.status not in {400, 404, 409, 422}}
        if not execution.get('claimed'):
            return {'ok': True, 'code': 0, 'msg': '本次计划已领取，跳过重复触发', 'skipped': True}
        task['_execution'] = execution
    else:
        await _safe_started(client, task_id)
    try:
        result = await task_handler(task)
    except Exception as error:
        logger.warning('任务执行异常 task_id=%s type=%s', task_id, type(error).__name__)
        result = {'ok': False, 'status': 'failed', 'reason': '执行器异常，未确认发送结果'}
    ok = not (isinstance(result, dict) and result.get('ok') is False)
    if execution:
        status = result.get('status', 'success' if ok else 'failed') if isinstance(result, dict) else 'failed'
        if not ok and status in {'success', 'accepted', 'submitted'}:
            status = 'failed'
        try:
            saved = await client.finish_execution(execution['run_id'], execution['token'], status,
                                                 str(result.get('reason', ''))[:240] if isinstance(result, dict) else '')
            status = saved['status']
        except ApiClientError:
            # Claim remains consumed. Never repeat the browser action to repair accounting.
            return {'ok': False, 'code': 2007, 'status': 'uncertain', 'retryable': False, 'msg': '执行结果未能保存，请核实；不会重发'}
        return {'ok': status in {'success', 'accepted', 'submitted'}, 'code': 0 if status in {'success', 'accepted', 'submitted'} else 2005,
                'status': status, 'retryable': False, 'detail': {'result': result}, 'msg': '执行结果已记录'}
    await _safe_result(client, task_id, ok=ok)
    return {'ok': ok, 'code': 0 if ok else 2005, 'detail': {'result': result}, 'msg': '执行成功' if ok else '执行失败'}


async def _safe_started(client, task_id: str) -> None:
    try:
        await client.mark_started(task_id)
    except ApiClientError:
        logger.warning("mark_started 失败：%s", task_id)


async def _safe_result(client, task_id: str, ok: bool) -> None:
    try:
        await client.mark_result(task_id, ok)
    except ApiClientError:
        logger.warning("mark_result 失败：%s ok=%s", task_id, ok)


def main() -> None:
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s %(levelname)s %(name)s %(message)s",
    )
    parser = argparse.ArgumentParser(description="执行一个计划任务")
    parser.add_argument("--task-id", required=True, help="ScheduledTask.task_id")
    parser.add_argument('--scheduled-for', default=None, help='原计划触发时间（带时区的 ISO 时间）')
    args = parser.parse_args()
    resp = asyncio.run(run_task(args.task_id, args.scheduled_for))
    raise SystemExit(0 if resp["ok"] else 1)


if __name__ == "__main__":
    main()
