"""控制台持久层的补充初始化：部分唯一索引 + 默认种子数据。

Tortoise 不支持声明式“部分唯一索引”（带 WHERE 条件），这里在建表后用原生
SQL 补建；SQLite 与 PostgreSQL 均支持相同的 ``CREATE UNIQUE INDEX ... WHERE``
语法，仅布尔字面量不同（SQLite 用 1，PostgreSQL 直接用列名）。

由 ``db.init_db.init_db()`` 在 ``generate_schemas`` 之后调用；属部署期一次性动作。
"""

from __future__ import annotations

from tortoise import connections

from .domain_models import TaskQuotaPolicy


# 每条：索引名 -> (表, 列表达式, sqlite 的 WHERE, postgres 的 WHERE)
_PARTIAL_UNIQUE_INDEXES = (
    (
        "uq_users_email_lookup_hash",
        "users",
        "email_lookup_hash",
        "email_lookup_hash IS NOT NULL",
        "email_lookup_hash IS NOT NULL",
    ),
    (
        "uq_task_quota_initial_user",
        "task_quota_grants",
        "user_id",
        "is_initial = 1",
        "is_initial",
    ),
    (
        "uq_enabled_task_schedule",
        "spark_tasks",
        "douyin_account_id, target_name, send_time",
        "enabled = 1",
        "enabled",
    ),
)


async def create_console_indexes() -> None:
    """补建部分唯一索引（幂等，IF NOT EXISTS）。"""
    conn = connections.get("default")
    dialect = conn.capabilities.dialect
    for name, table, columns, sqlite_where, pg_where in _PARTIAL_UNIQUE_INDEXES:
        where = sqlite_where if dialect == "sqlite" else pg_where
        await conn.execute_query(
            f"CREATE UNIQUE INDEX IF NOT EXISTS {name} "
            f"ON {table} ({columns}) WHERE {where}"
        )


async def seed_console_defaults() -> None:
    """写入默认任务额度策略（单例 id=1），已存在则跳过。"""
    if await TaskQuotaPolicy.filter(id=1).exists():
        return
    await TaskQuotaPolicy.create(
        id=1,
        default_amount=5,
        default_duration_days=None,
        max_saved_tasks=20,
    )
