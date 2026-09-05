"""计划任务持久化模型（Tortoise-ORM）。

表 ``scheduled_tasks``：通用计划任务调度层的唯一数据来源。调度器只把 ``task_id``
写进各平台触发器，执行时凭 ``task_id`` 回查本表获取 ``event_category`` 与 ``params``。

约定（与 db 包一致）：
- 主键为 UUID 字符串（``CharField(pk=True, default=uuid_string)``）。
- 时间统一 naive-UTC（``TORTOISE_ORM`` 全程 ``use_tz=False``）。
- ``cron_expr`` 存标准 5 段 cron，按 Asia/Shanghai 解释（换算见 ``crud``）。
"""

from __future__ import annotations

import uuid

from tortoise import fields, models


def uuid_string() -> str:
    return str(uuid.uuid4())


class ScheduledTask(models.Model):
    """计划任务：一行即一个「按 cron 触发某 event_category」的定时任务。"""

    task_id = fields.CharField(
        max_length=36, pk=True, default=uuid_string,
        description="任务唯一 ID；同时作为各平台触发器名/事件载荷标识",
    )
    cron_expr = fields.CharField(
        max_length=128, description="标准 5 段 cron，按 Asia/Shanghai 解释",
    )
    event_category = fields.CharField(
        max_length=64, index=True,
        description="事件类别，路由到 registry 中同名 handler，如 spark_renew",
    )
    params = fields.JSONField(
        null=True, description="传给事件 handler 的通用透传参数（JSON，可空）",
    )
    target_env = fields.CharField(
        max_length=16, default="linux",
        description="调度后端：windows / linux / fc",
    )
    enabled = fields.BooleanField(default=True, description="是否启用（禁用则移除触发器）")
    status = fields.CharField(
        max_length=16, default="pending",
        description="最近一次执行状态：pending/running/success/failed",
    )
    last_run_at = fields.DatetimeField(null=True, description="上次执行时间（UTC）")
    next_run_at = fields.DatetimeField(null=True, description="下次预计执行时间（UTC）")
    created_at = fields.DatetimeField(auto_now_add=True, description="创建时间")
    updated_at = fields.DatetimeField(auto_now=True, description="更新时间")

    class Meta:
        table = "scheduled_tasks"
        ordering = ["created_at"]
