"""数据库模型定义。

使用 Tortoise-ORM，可同时适配 SQLite（本地调试）与 PostgreSQL（生产环境）。
连接地址通过环境变量 DATABASE_URL 指定，默认使用本地 SQLite 文件 db.sqlite3。

    # 本地调试（默认，无需设置环境变量）
    python -m db.init_db

    # 生产环境使用 PostgreSQL
    DATABASE_URL=postgres://user:password@127.0.0.1:5432/dbname python -m db.init_db
"""

import os
import time

# 统一进程时区为 UTC：Tortoise + SQLite 对 aware datetime 的本地化序列化会破坏
# 范围比较，这里以 use_tz=False + 全程 naive-UTC 规避（PostgreSQL 亦一致）。
os.environ.setdefault("TZ", "UTC")
try:
    time.tzset()
except AttributeError:  # 非 POSIX 平台
    pass
os.environ["USE_TZ"] = "False"
os.environ["TIMEZONE"] = "UTC"

from tortoise import fields, models

# 数据库连接地址：本地默认 SQLite，可通过 DATABASE_URL 切换为 PostgreSQL
DATABASE_URL = os.getenv("DATABASE_URL", "sqlite://db.sqlite3")

# Tortoise-ORM 全局配置（初始化脚本 / 应用入口 / aerich 迁移共用）
TORTOISE_ORM = {
    "connections": {"default": DATABASE_URL},
    "apps": {
        "models": {
            # 模型所在模块：基础表 + 控制台业务表（由 spark_console 迁移）
            "models": ["db.models", "db.console_models", "task.models"],
            "default_connection": "default",
        }
    },
    # 全程 naive-UTC：数据库存无时区时间，业务层保证写入/比较均为 UTC
    "use_tz": False,
    "timezone": "UTC",
}


# 系统配置键定义：config_key -> 默认值。
# 键集合在首次建表（db/init_db.py）时即固定，运行期仅更新与查询值，不增删键。
# 需要新增配置时，在此追加键与默认值，再执行一次 python -m db.init_db 即可。
SYSTEM_CONFIG_KEYS: dict[str, str] = {
    "browser_concurrency": "4",  # 浏览器并发数

    # ═══ 云函数浏览器（browser/cloud.py）运行期配置 ═══
    # 部署产出的 HTTP 触发器公网地址；安装向导完成后回写此键，云端模式据此签名调用。
    "fc_function_url": "",        # 如 https://<fn>-<uid>.<region>.fcapp.run
    "fc_qualifier": "LATEST",     # 云函数版本/别名（Get/DeleteSession 用）

    # ═══ FC 自动部署向导（fc/provision_image_function.py）配置 ═══
    # 键的字段元数据（类型/默认值/所属向导步骤）以该模块的 CONFIG_FIELDS 为准，
    # 此处仅注册键与默认字符串（值默认取 CONFIG_FIELDS 的 default）。
    # ── 向导第 1 步：账号与角色校验 ──
    "platform_access_key_id": "",            # 平台 AK（AssumeRole 发起方）
    "platform_access_key_secret": "",        # 平台 SK
    "target_account_id": "",                 # 目标账号主账号 ID
    "assume_role_arn": "",                   # 目标账号内、信任平台账号的角色 ARN
    "role_session_name": "plat-provision",   # AssumeRole 会话名
    "region": "cn-hangzhou",                 # 地域
    "function_exec_role_arn": "",            # 函数执行角色 ARN（可选，留空走服务关联角色）
    "auto_create_slr": "true",               # 是否自动创建 FC 服务关联角色
    # ── 向导第 2 步：VPC 网络链路 ──
    "vpc_cidr": "172.16.0.0/16",             # VPC 网段
    "vswitch_cidr": "172.16.0.0/20",         # 交换机网段
    "zone_id": "",                           # 可用区（留空自动选择）
    "eip_bandwidth_mbps": "5",               # EIP 带宽峰值 Mbps（按流量计费上限）
    # ── 向导第 3 步：函数/镜像/触发器 ──
    "function_name": "",                     # 函数名（字母开头 1~64 位）
    "image_url": "",                         # 容器镜像完整地址
    "image_registry_username": "",           # 私有仓库用户名（公开镜像留空）
    "image_registry_password": "",           # 私有仓库密码（公开镜像留空）
    "container_port": "9000",                # 镜像内 HTTP Server 监听端口
    "cpu_vcores": "1.0",                     # CPU 核数
    "memory_size_mb": "1536",                # 内存 MB（64 倍数，与 CPU 比例 1:1~1:4）
    "timeout_seconds": "60",                 # 函数超时（s）
    "disk_size_mb": "512",                   # 磁盘：512 或 10240
    "affinity_header_field_name": "sessionid",  # Header 会话亲和键名
    "session_concurrency_per_instance": "1",    # 单实例并发 Session 数
    "session_ttl_seconds": "600",               # Session 生命周期（s）
    "session_idle_timeout_seconds": "30",       # Session 空闲时长（s）
    "disable_session_id_reuse": "false",        # 禁用 SessionID 复用
    "trigger_name": "default-http",             # HTTP 触发器名
    "trigger_methods": '["GET", "POST"]',       # 触发器允许的 HTTP 方法（JSON 数组）
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
