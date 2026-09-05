"""统一的时间工具：全程 naive-UTC。

数据库层使用 ``use_tz=False``，所有写入/比较的时间必须是“无时区的 UTC”，
避免 SQLite 对 aware datetime 的本地化序列化破坏范围比较；PostgreSQL 亦一致。
"""

from __future__ import annotations

from datetime import datetime, timezone


def utcnow() -> datetime:
    """当前 UTC 时间（naive）。"""
    return datetime.now(timezone.utc).replace(tzinfo=None)


def to_naive_utc(value: datetime | None) -> datetime | None:
    """把任意 datetime 归一化为 naive-UTC；aware 先转 UTC 再去除时区，naive 原样返回。"""
    if value is None:
        return None
    if value.tzinfo is not None:
        return value.astimezone(timezone.utc).replace(tzinfo=None)
    return value
