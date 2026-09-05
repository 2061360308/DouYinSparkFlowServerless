"""内置 handler 登记。

本期仅提供：
- ``noop``：空操作，用于闭环冒烟测试。
- ``spark_renew``：续火花占位。本期不迁移其脚本与逻辑，触发即抛
  ``NotImplementedError``；后续把 core/tasks.py 的 runTasks 接进来即可。

新增事件：在此模块用 ``@registry.handler("event_category")`` 登记新的 handler。
"""

from __future__ import annotations

import logging

from ..registry import handler

logger = logging.getLogger(__name__)


@handler("noop")
async def _noop(task: dict) -> dict:
    """空操作：仅记录一次日志，返回任务的 params。"""
    logger.info("noop handler 执行: task_id=%s", task.get("task_id"))
    return {"handled": "noop", "params": task.get("params")}


@handler("spark_renew")
async def _spark_renew(task: dict) -> None:
    """续火花占位：本期未接入具体逻辑。"""
    raise NotImplementedError(
        "spark_renew 尚未接入：请将 core/tasks.py 的 runTasks 封装为 handler 后再启用"
    )
