"""通用计划任务调度层。

只负责「何时 / 在哪种环境 / 触发哪个 event_category / 携带 task_id」：

- 存储层：``models.ScheduledTask``（Tortoise-ORM），保存任务全量元数据。
- 调度层：``dispatcher`` 按 ``target_env`` 把「仅带 task_id」的触发器注册到
  Windows 计划任务 / Linux crontab / 阿里云 EventBridge 定时调度。
- 执行层：``run`` 被唤醒后凭 task_id 查库 → 按 ``event_category`` 路由到
  ``registry`` 中登记的 handler → 传入 ``params`` 执行。

本层不含任何业务事件实现；续火花等具体逻辑后续以 handler 形式单独接入。
cron 一律为标准 5 段表达式，按 Asia/Shanghai 解释；数据库时间统一 naive-UTC。
"""

from . import handlers as handlers  # noqa: F401  触发内置 handler 注册

__all__ = ["handlers"]
