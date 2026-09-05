"""执行入口：被各平台触发器唤醒后凭 task_id 查库并执行。

本地：``python -m core.task.run --task-id <task_id>``
FC：函数 handler 从 EventBridge 事件载荷取 ``task_id`` 后调用 ``run_task``。

流程：查库 → 读 event_category → registry 路由 handler → 传 params 执行
     → 回写 status / last_run_at / next_run_at。
"""

from __future__ import annotations

import argparse
import asyncio
import logging

from . import registry
from .crud import ScheduledTaskDB

logger = logging.getLogger(__name__)


async def run_task(task_id: str) -> dict:
    """执行一个计划任务；返回统一结构 ``{"ok","code","detail","msg"}``。"""
    task = await ScheduledTaskDB.get(task_id)
    if task is None:
        logger.error("task 不存在：%s", task_id)
        return {"ok": False, "code": 2002, "detail": None, "msg": "task 不存在"}

    if not task.get("enabled", False):
        logger.warning("task 已禁用，跳过执行：%s", task_id)
        return {"ok": False, "code": 2003, "detail": task, "msg": "task 已禁用"}

    category = task["event_category"]
    try:
        handler = registry.get(category)
    except registry.UnknownEventCategory:
        logger.error("未注册的 event_category：%s (task_id=%s)", category, task_id)
        await ScheduledTaskDB.mark_result(task_id, ok=False)
        return {"ok": False, "code": 2004, "detail": task,
                "msg": f"未注册的 event_category：{category}"}

    await ScheduledTaskDB.mark_started(task_id)
    try:
        result = await handler(task)
    except Exception as error:  # noqa: BLE001  执行面兜底：任何异常都回写 failed
        logger.exception("task 执行失败：%s", task_id)
        await ScheduledTaskDB.mark_result(task_id, ok=False)
        return {"ok": False, "code": 2005, "detail": {"error": str(error)},
                "msg": "执行失败"}

    await ScheduledTaskDB.mark_result(task_id, ok=True)
    logger.info("task 执行成功：%s", task_id)
    return {"ok": True, "code": 0, "detail": {"result": result}, "msg": "执行成功"}


def main() -> None:
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s %(levelname)s %(name)s %(message)s",
    )
    parser = argparse.ArgumentParser(description="执行一个计划任务")
    parser.add_argument("--task-id", required=True, help="ScheduledTask.task_id")
    args = parser.parse_args()
    resp = asyncio.run(run_task(args.task_id))
    raise SystemExit(0 if resp["ok"] else 1)


if __name__ == "__main__":
    main()
