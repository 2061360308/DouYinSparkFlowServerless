"""system_config（系统配置）表的读写操作类。

系统配置键在初始化建表时即固定（见 ``db.models.SYSTEM_CONFIG_KEYS``），
运行期仅更新与查询值。每个注册键暴露为一个配置项类，提供
classmethod ``get()`` / ``set()``（实时访问数据库、无缓存、不阻塞事件循环）：

    from core.db import BrowserConcurrency

    concurrency = await BrowserConcurrency.get()   # 读取，int(4)，记录缺失时回落默认值
    await BrowserConcurrency.set(8)                # 写入，自动转字符串落库

- 配置项类仅需声明 ``KEY``（与 SYSTEM_CONFIG_KEYS 对应）与可选 ``TYPE``
  （get() 的返回值类型转换，默认 str）；
- 默认值统一取自 ``SYSTEM_CONFIG_KEYS``，不重复登记。

新增配置项步骤：
    1. db/models.py 的 SYSTEM_CONFIG_KEYS 追加 键 -> 默认值；
    2. 本文件顶部按模板追加一个配置项类（两行）；
    3. 可选：db/__init__.py 导出该类；执行一次 python -m core.db.init_db 写入默认值。

SystemConfigDB 保留通用按键读写 get_value/set_value，
适合按 key 字符串动态访问（未知键 set 会抛 ValueError）。
"""

from typing import Any, Optional

from tortoise.transactions import in_transaction

from .config import SYSTEM_CONFIG_KEYS
from .connection import with_db
from .models import SystemConfig
from .models.system import SystemSecret
from .config_secrets import SECRET_KEYS, encrypt, decrypt


class _ConfigItemBase:
    """配置项基类：子类声明 KEY（键名）与可选 TYPE（get 返回值类型）。

    无需重写方法，直接调用 ``await SubCls.get()`` / ``await SubCls.set(v)``。
    """

    KEY = ""
    TYPE = str

    @classmethod
    @with_db
    async def get(cls):
        """读取配置值；记录不存在时返回 SYSTEM_CONFIG_KEYS 中的默认值。"""
        row = await SystemConfig.get_or_none(config_key=cls.KEY)
        raw = row.config_value if row is not None else SYSTEM_CONFIG_KEYS.get(cls.KEY, "")
        try:
            return cls.TYPE(raw)
        except (TypeError, ValueError):
            return raw

    @classmethod
    @with_db
    async def set(cls, value: Any) -> None:
        """写入配置值（统一转字符串存储；记录不存在时自动创建）。"""
        text = "" if value is None else str(value)
        row = await SystemConfig.get_or_none(config_key=cls.KEY)
        if row is None:
            await SystemConfig.create(config_key=cls.KEY, config_value=text)
        else:
            row.config_value = text
            await row.save(update_fields=["config_value"])


# ---------------------------------------------------------------------------
# 具体配置项类（与 SYSTEM_CONFIG_KEYS 一一对应）
# ---------------------------------------------------------------------------


class BrowserConcurrency(_ConfigItemBase):
    """系统配置项：浏览器并发数（键 browser_concurrency，默认 4）。"""

    KEY = "browser_concurrency"
    TYPE = int


class FcFunctionUrl(_ConfigItemBase):
    """系统配置项：云函数 HTTP 触发器公网地址（键 fc_function_url）。"""

    KEY = "fc_function_url"
    TYPE = str


class FcQualifier(_ConfigItemBase):
    """系统配置项：云函数版本/别名（键 fc_qualifier，默认 LATEST）。"""

    KEY = "fc_qualifier"
    TYPE = str


# ---------------------------------------------------------------------------
# 通用按键读写（供动态按键字符串访问；常规场景建议使用上面的配置项类）
# ---------------------------------------------------------------------------


class SystemConfigDB:
    """系统配置表通用读写操作类（全部为静态方法，无需实例化）。"""

    @staticmethod
    @with_db
    async def get_value(key: str, default: Optional[str] = None) -> Optional[str]:
        """按配置键读取原始字符串值；记录不存在或键未注册时返回 default。"""
        if key in SECRET_KEYS:
            secret = await SystemSecret.get_or_none(key=key)
            if secret:
                return decrypt(secret)
        row = await SystemConfig.get_or_none(config_key=key)
        return row.config_value if row is not None else default

    @staticmethod
    @with_db
    async def get_many(keys: Optional[list[str]] = None) -> dict[str, str]:
        """批量读取配置：返回 {key: value}，缺记录回落 SYSTEM_CONFIG_KEYS 默认值。

        Args:
            keys: 要读取的键列表；为 None 时读取全部已注册键。
        """
        key_list = list(keys) if keys is not None else list(SYSTEM_CONFIG_KEYS)
        unknown = [k for k in key_list if k not in SYSTEM_CONFIG_KEYS]
        if unknown:
            raise ValueError(f"未知系统配置键: {unknown}，可用键: {sorted(SYSTEM_CONFIG_KEYS)}")
        rows = await SystemConfig.filter(config_key__in=key_list).values(
            "config_key", "config_value"
        )
        stored = {row["config_key"]: row["config_value"] for row in rows}
        for secret in await SystemSecret.filter(key__in=list(SECRET_KEYS.intersection(key_list))):
            stored[secret.key] = decrypt(secret)
        return {k: stored.get(k, SYSTEM_CONFIG_KEYS.get(k, "")) for k in key_list}

    @staticmethod
    @with_db
    async def public_values() -> dict:
        # No decryption on the admin read path, even when a key needs recovery.
        values = await SystemConfigDB.get_many([k for k in SYSTEM_CONFIG_KEYS if k not in SECRET_KEYS])
        configured = {}
        for key in SECRET_KEYS:
            legacy = await SystemConfig.get_or_none(config_key=key)
            configured[key] = await SystemSecret.exists(key=key) or bool(legacy and legacy.config_value)
            values[key] = ''
        return {'values': values, 'secret_configured': configured}

    @staticmethod
    @with_db
    async def migrate_secrets() -> None:
        """Idempotent migration; encryption and clearing plaintext commit together."""
        async with in_transaction():
            for row in await SystemConfig.filter(config_key__in=list(SECRET_KEYS)).select_for_update():
                if row.config_value:
                    secret = await SystemSecret.get_or_none(key=row.config_key)
                    if secret:
                        decrypt(secret)  # Never discard a fallback if the primary cannot be read.
                    else:
                        await SystemSecret.create(key=row.config_key, **encrypt(row.config_key, row.config_value))
                    row.config_value = ''
                    await row.save(update_fields=['config_value'])

    @staticmethod
    @with_db
    async def set_many(values: dict[str, Any]) -> None:
        """批量写入配置：全部成功才提交，任意一项失败则整批回滚。"""
        unknown = [k for k in values if k not in SYSTEM_CONFIG_KEYS]
        if unknown:
            raise ValueError(f"未知系统配置键: {unknown}，可用键: {sorted(SYSTEM_CONFIG_KEYS)}")
        async with in_transaction():
            for key, value in values.items():
                # 嵌套调用复用当前事务；连接由外层 with_db 保持。
                await SystemConfigDB.set_value(key, value)

    @staticmethod
    @with_db
    async def set_value(key: str, value: Any) -> None:
        """设置配置项（键须在 SYSTEM_CONFIG_KEYS 中注册），值以字符串形式存储。

        Raises:
            ValueError: key 不在 SYSTEM_CONFIG_KEYS 注册表中。
        """
        if key not in SYSTEM_CONFIG_KEYS:
            raise ValueError(
                f"未知系统配置键: {key!r}，可用键: {sorted(SYSTEM_CONFIG_KEYS)}"
            )
        text = "" if value is None else str(value)
        if key in SECRET_KEYS:
            async with in_transaction():
                if text:
                    await SystemSecret.update_or_create(key=key, defaults=encrypt(key, text))
                else:
                    await SystemSecret.filter(key=key).delete()
                await SystemConfig.update_or_create(config_key=key, defaults={'config_value': ''})
            return
        row = await SystemConfig.get_or_none(config_key=key)
        if row is None:
            await SystemConfig.create(config_key=key, config_value=text)
        else:
            row.config_value = text
            await row.save(update_fields=["config_value"])
