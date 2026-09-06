"""数据库初始化模块。

根据 db/models.py 中定义的模型创建数据库表，并写入 SYSTEM_CONFIG_KEYS
中的默认系统配置。可重复执行：已存在的表与配置不会被覆盖。

用法：
    python -m core.db                                         # 默认 SQLite（本地调试）
    DATABASE_URL=postgres://... python -m core.db             # PostgreSQL（生产环境）

编程调用：
    from core.db.init_db import init_db
    await init_db()
"""

import asyncio

from tortoise import Tortoise

from .config import SYSTEM_CONFIG_KEYS, TORTOISE_ORM
from .domain_init import create_console_indexes, seed_console_defaults
from .models import SystemConfig


async def init_db() -> None:
    """初始化数据库：建表并写入缺失的默认配置。"""
    # 初始化数据库连接（_create_db=True：PostgreSQL 下若库不存在会自动创建）
    await Tortoise.init(config=TORTOISE_ORM, _create_db=True)

    # 依据模型创建表结构（safe=True：已存在的表自动跳过）
    await Tortoise.generate_schemas(safe=True)

    # 补建部分唯一索引（Tortoise 不支持声明式部分索引）
    await create_console_indexes()

    # 写入默认配置（仅当对应配置项尚不存在时，键集固定见 models.SYSTEM_CONFIG_KEYS）
    for key, value in SYSTEM_CONFIG_KEYS.items():
        if not await SystemConfig.exists(config_key=key):
            await SystemConfig.create(config_key=key, config_value=value)
            print(f"[init] 写入默认配置: {key} = {value}")

    # 写入控制台默认种子数据（任务额度策略单例）
    await seed_console_defaults()

    await Tortoise.close_connections()
    print("数据库初始化完成。")


def main() -> None:
    asyncio.run(init_db())
