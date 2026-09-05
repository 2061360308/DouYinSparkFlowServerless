"""控制台服务层（异步，基于 Tortoise 模型）。

由 spark_console.services 迁移：把 SQLAlchemy Session 改为直接 await Tortoise
模型查询/写入，业务规则（额度/安全间隔/状态机等）保持一致。
"""

from __future__ import annotations


class ServiceError(Exception):
    """服务层基础异常。"""


class NotFound(ServiceError):
    """资源不存在。"""


class Conflict(ServiceError):
    """并发/唯一性冲突。"""


class ValidationError(ServiceError):
    """输入或业务校验失败。"""
