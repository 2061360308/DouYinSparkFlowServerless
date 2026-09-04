"""数据库连接生命周期管理与 ``with_db`` 装饰器。

被 ``with_db`` 装饰的方法执行前自动建立数据库连接
（SQLite 文件 / PostgreSQL 库不存在时自动创建），执行结束后自动释放连接；
通过引用计数支持并发调用与嵌套调用（方法内再调用其他带 ``with_db``
的方法不会提前关闭连接），业务代码无需关心连接的开合。

使用方法：

    class MyDB:
        @staticmethod
        @with_db
        async def do_something() -> None:
            ...
"""

import asyncio
import functools
from typing import Any, Callable, TypeVar

from tortoise import Tortoise

from .models import TORTOISE_ORM

_conn_lock = asyncio.Lock()  # 保护初始化过程，避免并发重复连接
_db_ready = False  # 连接是否已建立
_conn_refs = 0  # 当前占用连接的调用方数量（实现可重入/计数式释放）

T = TypeVar("T")


async def _ensure_connected() -> None:
    """确保数据库已连接（幂等、并发安全）。"""
    global _db_ready
    if _db_ready:
        return
    async with _conn_lock:
        if not _db_ready:
            # _create_db=True：SQLite 文件或 PostgreSQL 库不存在时自动创建
            await Tortoise.init(config=TORTOISE_ORM, _create_db=True)
            _db_ready = True


async def _release_connected() -> None:
    """引用计数减一，所有调用方结束后关闭连接。"""
    global _db_ready, _conn_refs
    _conn_refs -= 1
    if _conn_refs <= 0:
        _conn_refs = 0
        await Tortoise.close_connections()
        _db_ready = False


def with_db(func: Callable[..., Any]) -> Callable[..., Any]:
    """装饰器：为被装饰的（静态）方法自动注入数据库实例。

    方法执行前建立连接、执行后释放；嵌套调用不会提前关闭连接。
    """

    @functools.wraps(func)
    async def wrapper(*args: Any, **kwargs: Any):
        global _conn_refs
        await _ensure_connected()
        _conn_refs += 1
        try:
            return await func(*args, **kwargs)
        finally:
            await _release_connected()

    return wrapper
