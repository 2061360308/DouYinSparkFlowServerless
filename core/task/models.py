"""计划任务模型兼容入口。

实际模型已迁移至 ``core.db.models.scheduled``，此处保留重导出以兼容旧导入。
"""

from core.db.models.scheduled import ScheduledTask

__all__ = ["ScheduledTask"]
