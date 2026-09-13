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

from .config import DATABASE_URL, TORTOISE_ORM

_conn_lock = asyncio.Lock()  # 保护初始化过程，避免并发重复连接
_db_ready = False  # 连接是否已建立
_conn_refs = 0  # 当前占用连接的调用方数量（实现可重入/计数式释放）

T = TypeVar("T")


async def _ensure_connected(enable_global_fallback: bool = False) -> None:
    """确保数据库已连接（幂等、并发安全）。

    enable_global_fallback: 供长驻服务（FastAPI）开启 Tortoise 全局回退上下文，
    使 lifespan 后台任务初始化的连接能被各请求任务复用（Tortoise 1.x 要求）。
    """
    global _db_ready
    if _db_ready:
        return
    async with _conn_lock:
        if not _db_ready:
            # 自动建库仅用于本地 SQLite 开发；PostgreSQL（含 Neon 等托管库）
            # 已由服务商预建数据库，_create_db=True 会执行 CREATE DATABASE 报
            # DuplicateDatabase，表结构统一由 init_db（python -m core.db）创建。
            _create_db = DATABASE_URL.startswith("sqlite")
            await Tortoise.init(
                config=TORTOISE_ORM,
                _create_db=_create_db,
                _enable_global_fallback=enable_global_fallback,
            )
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


async def open_persistent() -> None:
    """服务常驻模式：建立连接并钉住一个永久引用。

    供长驻服务（如 FastAPI lifespan 启动）调用，使后续每个 ``with_db`` 调用
    结束时引用计数不会归零、连接保持温热，避免 serverless 每请求 init/close
    的高开销。与 ``close_persistent`` 成对使用。
    """
    global _conn_refs
    await _ensure_connected(enable_global_fallback=True)
    _conn_refs += 1


async def close_persistent() -> None:
    """释放常驻引用；无其他占用时关闭连接（供服务停机调用）。"""
    await _release_connected()
