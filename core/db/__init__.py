"""数据库读写管理模块（包）。

数据层整体收敛于 db 包：模型、连接管理、初始化脚本与各表读写操作类。
表操作类内全部为静态方法，无需实例化即可直接调用；方法统一使用
``@with_db`` 装饰器自动维护连接。并发正确性由数据库机制保证
（单条原子 SQL + 主键/唯一约束），不依赖应用层锁。

    db/
    ├── __init__.py            # 统一导出，兼容 ``from core.db import XxxDB``
    ├── __main__.py            # CLI 入口：python -m core.db（初始化数据库）
    ├── connection.py          # 连接生命周期管理 + with_db 装饰器
    ├── models.py              # 数据库模型 + TORTOISE_ORM + SYSTEM_CONFIG_KEYS
    ├── init_db.py             # 初始化逻辑（init_db()），供 __main__ 与编程调用
    ├── browser_instance_db.py # browser_instance 表操作类 BrowserInstanceDB
    └── system_config_db.py    # system_config 表操作类 SystemConfigDB / 配置项类

新增表时：在 models.py 定义模型，在 db/ 下新建 ``<table>_db.py``，
仿照现有操作类提供读写方法即可。

用法示例：

    import asyncio

    from core.db import BrowserConcurrency, BrowserInstanceDB

    async def main():
        # 系统配置项类：实时访问数据库，无缓存
        n = await BrowserConcurrency.get()    # 读取，int
        await BrowserConcurrency.set(8)       # 写入

        # 浏览器实例管理
        ret = await BrowserInstanceDB.create("sess-001", cfg="aGVsbG8=", pid=123)
        print(ret)  # {'ok': True, 'code': 0, 'detail': {...}, 'msg': '操作成功'}
        print(await BrowserInstanceDB.get("sess-001"))
        await BrowserInstanceDB.delete("sess-001")

    asyncio.run(main())

注意：首次使用前请先执行 ``python -m core.db`` 完成建表。
"""

from .browser_instance_db import (
    BrowserInstanceDB,
    ERR_SESSION_EXISTS,
    ERR_SESSION_NOT_FOUND,
    OK,
)
from .connection import with_db
from .models import SYSTEM_CONFIG_KEYS
from .system_config_db import (
    BrowserConcurrency,
    FcFunctionUrl,
    FcQualifier,
    SystemConfigDB,
)

__all__ = [
    "with_db",
    "SYSTEM_CONFIG_KEYS",
    "BrowserInstanceDB",
    "SystemConfigDB",
    "BrowserConcurrency",
    "FcFunctionUrl",
    "FcQualifier",
    "OK",
    "ERR_SESSION_EXISTS",
    "ERR_SESSION_NOT_FOUND",
]
