"""DB 版失败/请求限流（替代内存 FailedAttemptLimiter，跨无状态实例正确）。

用 ``rate_limit_attempts`` 表：每次失败插一行，按 (scope,key) 在滑动窗内计数，
过期行惰性清理。所有方法为异步，走 db/ 的连接管理。
"""

from __future__ import annotations

from datetime import datetime, timedelta, timezone

from core.db.connection import with_db
from core.db.domain_models import RateLimitAttempt


def _utc_now() -> datetime:
    return datetime.now(timezone.utc)


class RateLimiter:
    def __init__(self, limit: int = 10, window: timedelta = timedelta(minutes=10)):
        self.limit = limit
        self.window = window

    @with_db
    async def allow(self, scope: str, key: str) -> bool:
        cutoff = _utc_now() - self.window
        await RateLimitAttempt.filter(
            scope=scope, key=key, created_at__lt=cutoff
        ).delete()
        recent = await RateLimitAttempt.filter(
            scope=scope, key=key, created_at__gte=cutoff
        ).count()
        return recent < self.limit

    @with_db
    async def record_failure(self, scope: str, key: str) -> None:
        await RateLimitAttempt.create(scope=scope, key=key)

    @with_db
    async def clear(self, scope: str, key: str) -> None:
        await RateLimitAttempt.filter(scope=scope, key=key).delete()
