"""system_config（系统配置）表的读写操作类。

系统配置键在初始化建表时即固定（见 ``db.models.SYSTEM_CONFIG_KEYS``），
运行期仅更新与查询值。每个注册键暴露为一个配置项类，提供
classmethod ``get()`` / ``set()``（实时访问数据库、无缓存、不阻塞事件循环）：

    from db import BrowserConcurrency

    concurrency = await BrowserConcurrency.get()   # 读取，int(4)，记录缺失时回落默认值
    await BrowserConcurrency.set(8)                # 写入，自动转字符串落库

- 配置项类仅需声明 ``KEY``（与 SYSTEM_CONFIG_KEYS 对应）与可选 ``TYPE``
  （get() 的返回值类型转换，默认 str）；
- 默认值统一取自 ``SYSTEM_CONFIG_KEYS``，不重复登记。

新增配置项步骤：
    1. db/models.py 的 SYSTEM_CONFIG_KEYS 追加 键 -> 默认值；
    2. 本文件顶部按模板追加一个配置项类（两行）；
    3. 可选：db/__init__.py 导出该类；执行一次 python -m db.init_db 写入默认值。

SystemConfigDB 保留通用按键读写 get_value/set_value，
适合按 key 字符串动态访问（未知键 set 会抛 ValueError）。
"""

from typing import Any, Optional

from .connection import with_db
from .models import SYSTEM_CONFIG_KEYS, SystemConfig


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


# ---------------------------------------------------------------------------
# 通用按键读写（供动态按键字符串访问；常规场景建议使用上面的配置项类）
# ---------------------------------------------------------------------------


class SystemConfigDB:
    """系统配置表通用读写操作类（全部为静态方法，无需实例化）。"""

    @staticmethod
    @with_db
    async def get_value(key: str, default: Optional[str] = None) -> Optional[str]:
        """按配置键读取原始字符串值；记录不存在或键未注册时返回 default。"""
        row = await SystemConfig.get_or_none(config_key=key)
        return row.config_value if row is not None else default

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
        row = await SystemConfig.get_or_none(config_key=key)
        if row is None:
            await SystemConfig.create(config_key=key, config_value=text)
        else:
            row.config_value = text
            await row.save(update_fields=["config_value"])
