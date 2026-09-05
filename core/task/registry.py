"""事件类别 → handler 注册表。

handler 签名：``async def handler(task: dict) -> Any``；``task`` 为 ``crud`` 返回的
任务字典（含 ``params``）。通过 ``@handler("event_category")`` 装饰器或 ``register``
登记；执行层 ``run`` 按任务的 ``event_category`` 查表调用。
"""

from __future__ import annotations

from typing import Awaitable, Callable, Dict

Handler = Callable[[dict], Awaitable]

_REGISTRY: Dict[str, Handler] = {}


class UnknownEventCategory(KeyError):
    """未注册的 event_category。"""


def register(category: str, func: Handler) -> None:
    """登记 handler；同名覆盖。"""
    _REGISTRY[category] = func


def handler(category: str) -> Callable[[Handler], Handler]:
    """装饰器形式登记 handler。"""

    def deco(func: Handler) -> Handler:
        register(category, func)
        return func

    return deco


def get(category: str) -> Handler:
    """取 handler；未注册抛 ``UnknownEventCategory``。"""
    try:
        return _REGISTRY[category]
    except KeyError as error:
        raise UnknownEventCategory(category) from error


def categories() -> list[str]:
    """已注册的事件类别列表。"""
    return sorted(_REGISTRY)
