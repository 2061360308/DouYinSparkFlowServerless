"""数据库模型定义。

使用 Tortoise-ORM，可同时适配 SQLite（本地调试）与 PostgreSQL（生产环境）。
连接地址通过环境变量 DATABASE_URL 指定，默认使用本地 SQLite 文件 db.sqlite3。

    # 本地调试（默认，无需设置环境变量）
    python -m db.init_db

    # 生产环境使用 PostgreSQL
    DATABASE_URL=postgres://user:password@127.0.0.1:5432/dbname python -m db.init_db
"""

import os

from tortoise import fields, models

# 数据库连接地址：本地默认 SQLite，可通过 DATABASE_URL 切换为 PostgreSQL
DATABASE_URL = os.getenv("DATABASE_URL", "sqlite://db.sqlite3")

# Tortoise-ORM 全局配置（初始化脚本 / 应用入口 / aerich 迁移共用）
TORTOISE_ORM = {
    "connections": {"default": DATABASE_URL},
    "apps": {
        "models": {
            "models": ["db.models"],  # 模型所在模块
            "default_connection": "default",
        }
    },
}


# 系统配置键定义：config_key -> 默认值。
# 键集合在首次建表（db/init_db.py）时即固定，运行期仅更新与查询值，不增删键。
# 需要新增配置时，在此追加键与默认值，再执行一次 python -m db.init_db 即可。
SYSTEM_CONFIG_KEYS: dict[str, str] = {
    "browser_concurrency": "4",  # 浏览器并发数
}


class SystemConfig(models.Model):
    """系统配置表（key-value 形式，便于后续扩展更多配置项，无需修改表结构）。"""

    id = fields.IntField(pk=True)
    config_key = fields.CharField(
        max_length=100, unique=True, description="配置键，如 browser_concurrency"
    )
    config_value = fields.TextField(description="配置值")
    created_at = fields.DatetimeField(auto_now_add=True, description="创建时间")
    updated_at = fields.DatetimeField(auto_now=True, description="更新时间")

    class Meta:
        table = "system_config"
        ordering = ["id"]

    @classmethod
    async def get_int(cls, key: str, default: int = 0) -> int:
        """按配置键读取整数值，便于应用代码使用。"""
        row = await cls.get_or_none(config_key=key)
        if row is None:
            return default
        try:
            return int(row.config_value)
        except ValueError:
            return default


class BrowserInstance(models.Model):
    """浏览器实例管理表：记录每个受管浏览器实例的运行信息。"""

    sessionid = fields.CharField(
        max_length=255, pk=True, description="浏览器会话 ID（主键）"
    )
    cfg = fields.TextField(description="浏览器配置（base64 编码的长字符串）")
    create_at = fields.DatetimeField(auto_now_add=True, description="创建时间")
    pid = fields.IntField(default=0, description="浏览器进程 ID，默认 0 表示尚未启动")

    class Meta:
        table = "browser_instance"
        ordering = ["-create_at"]
