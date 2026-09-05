"""业务事件 handler（注册进 task.registry，供 task.run 按 event_category 回调）。

导入本包即触发内置业务 handler 注册（组合根接线）：
- douyin_spark：续火任务执行（经 API 取数 + 连远程浏览器发送）。

task/ 保持通用、不依赖 core.handlers；执行入口(core.task.run)在启动时 import 本包填充注册表。
"""

from . import douyin_spark as douyin_spark  # noqa: F401  触发 @handler 注册

__all__ = ["douyin_spark"]
