"""浏览器实例管理器（唯一入口）：按部署环境选择本地/云函数后端，统一 acquire/get/destroy。

环境判别
--------
- 设置了环境变量 ``DouyinSparkDocker`` → **本地模式**（服务器 docker 部署）：可持久化
  管理 chrome OS 进程，起后台 reaper 做空闲/TTL 回收（有状态）。
- 未设置（Vercel 等 Serverless）→ **云函数模式**：对接 cloakbrowser-serverless，
  无跨请求内存状态，权威状态在 DB + FC（无状态）。

单例
----
类唯一：``__new__`` 恒返回同一实例；``await BrowserManager.get_instance()`` 是异步入口，
首次调用读取系统设置（并发数；云端另读函数 URL/AK 等）并构建对应后端，之后复用。

并发
----
本地/云端统一用 **DB 计数 + 直接拒绝**：``acquire`` 先尝试复用同 sessionid 的现有浏览器
（复用不占新增名额）；否则当 ``BrowserInstance`` 行数已达 ``browser_concurrency`` 时直接
返回“已达上限”，不做阻塞等待（适配无状态）。

返回结构（本地/云端一致）：
``{"ok","code","sessionid","ws_url","headers","mode","pid","msg"[, "fc_session_key"]}``
- 云端 ``headers`` 为 WS 握手签名头，``connect_over_cdp(ws_url, headers=headers)`` 直连；
- 本地 ``headers`` 恒为空 dict。

用法::

    from core.browser import BrowserManager

    mgr = await BrowserManager.get_instance()
    res = await mgr.acquire("douyin_10001", seed="12345", region="CN")
    if res["ok"]:
        ws, headers = res["ws_url"], res["headers"]
        # await playwright.chromium.connect_over_cdp(ws, headers=headers)
    ...
    await mgr.destroy("douyin_10001")
"""

from __future__ import annotations

import asyncio
import logging
import os
from typing import Any, Optional

logger = logging.getLogger("browser.manager")

# 结果码
OK = 0
ERR_BAD_ARG = 3000        # 入参非法
ERR_AT_CAPACITY = 3001    # 已达并发上限
ERR_NOT_READY = 3002      # 管理器未初始化
ERR_BACKEND = 3004        # 后端异常

# 环境标识：服务器 docker 部署时设置此环境变量以启用本地模式
DOCKER_ENV_FLAG = "DouyinSparkDocker"


def is_docker_deployment() -> bool:
    """是否为服务器 docker 部署（本地模式）。"""
    v = os.environ.get(DOCKER_ENV_FLAG)
    return bool(v) and str(v).strip().lower() not in ("", "0", "false", "no", "off")


def _to_int(value: Any, default: int) -> int:
    try:
        return int(str(value).strip())
    except (TypeError, ValueError):
        return default


class BrowserManager:
    """唯一的浏览器实例管理类（单例）。"""

    _instance: Optional["BrowserManager"] = None
    _lock = asyncio.Lock()

    def __new__(cls, *args: Any, **kwargs: Any) -> "BrowserManager":
        if cls._instance is None:
            cls._instance = super().__new__(cls)
        return cls._instance

    def __init__(self) -> None:
        # __new__ 保证单例；避免重复构造覆盖已就绪状态
        if getattr(self, "_constructed", False):
            return
        self._constructed = True
        self._ready = False
        self.mode: Optional[str] = None
        self.backend: Any = None
        self.concurrency = 4
        self.ttl = 600
        self.idle = 30

    # ------------------------------------------------------------------
    # 初始化 / 单例入口
    # ------------------------------------------------------------------
    @classmethod
    async def get_instance(cls) -> "BrowserManager":
        """获取唯一实例；首次调用读取配置并构建后端（并发安全，幂等）。"""
        inst = cls()  # 单例
        if inst._ready:
            return inst
        async with cls._lock:
            if not inst._ready:
                await inst._load_config()
        return inst

    async def _load_config(self) -> None:
        from core.db.system_config_db import SystemConfigDB

        base_keys = [
            "browser_concurrency",
            "session_ttl_seconds",
            "session_idle_timeout_seconds",
        ]
        cloud_keys = [
            "fc_function_url",
            "function_name",
            "region",
            "target_account_id",
            "platform_access_key_id",
            "platform_access_key_secret",
            "affinity_header_field_name",
            "fc_qualifier",
        ]
        docker = is_docker_deployment()
        vals = await SystemConfigDB.get_many(base_keys + ([] if docker else cloud_keys))

        self.concurrency = max(1, _to_int(vals["browser_concurrency"], 4))
        self.ttl = _to_int(vals["session_ttl_seconds"], 600)
        self.idle = _to_int(vals["session_idle_timeout_seconds"], 30)

        if docker:
            from .local import LocalBackend

            self.mode = "local"
            self.backend = LocalBackend(
                ttl_seconds=self.ttl, idle_timeout_seconds=self.idle
            )
            # 进程重启后清理死亡/超时实例；启动后台超时回收
            await self.backend.reconcile()
            await self.backend.start_reaper()
        else:
            from .cloud import CloudBackend

            self.mode = "cloud"
            self.backend = CloudBackend(
                function_url=vals["fc_function_url"],
                function_name=vals["function_name"],
                region=vals["region"],
                account_id=vals["target_account_id"],
                access_key_id=vals["platform_access_key_id"],
                access_key_secret=vals["platform_access_key_secret"],
                affinity_header=vals["affinity_header_field_name"] or "sessionid",
                qualifier=vals["fc_qualifier"] or "LATEST",
                start_timeout=180.0,  # /start 冷启动就绪上限（与 session ttl 解耦）
            )
        self._ready = True
        logger.info("BrowserManager 就绪：mode=%s concurrency=%s ttl=%s idle=%s",
                    self.mode, self.concurrency, self.ttl, self.idle)

    # ------------------------------------------------------------------
    # 对外能力
    # ------------------------------------------------------------------
    async def acquire(self, sessionid: str, **fingerprint: Any) -> dict:
        """申请浏览器（按业务 sessionid）。

        流程：复用现有可用浏览器（校验：本地进程存活+CDP 可达 / 云端 /json/version）→
        不可用则自动销毁重建 → 达并发上限则拒绝 → 否则新建并等就绪。

        指纹参数（均可选）：seed / region / locale / timezone / proxy /
        platform / headless / extra_args。

        返回统一结构 dict（见模块文档）。
        """
        if not self._ready:
            return self._err(ERR_NOT_READY, sessionid,
                             "管理器未初始化，请用 await BrowserManager.get_instance()")
        if not sessionid or not isinstance(sessionid, str):
            return self._err(ERR_BAD_ARG, sessionid, "sessionid 必须为非空字符串")

        fp = {k: v for k, v in fingerprint.items() if v is not None}
        if self.mode == "local":
            fp.setdefault("headless", True)  # 服务器环境通常无显示，默认无头

        try:
            reused = await self.backend.try_reuse(sessionid)
            if reused:
                return reused
            from core.db import BrowserInstanceDB

            if await BrowserInstanceDB.count() >= self.concurrency:
                return self._err(
                    ERR_AT_CAPACITY, sessionid,
                    f"已达浏览器并发上限（{self.concurrency}），请稍后重试或先销毁空闲会话",
                )
            return await self.backend.create(sessionid, fp)
        except Exception as e:  # noqa: BLE001
            logger.exception("acquire 失败 sessionid=%s", sessionid)
            return self._err(ERR_BACKEND, sessionid, f"申请浏览器失败: {e}")

    async def get(self, sessionid: str) -> Optional[dict]:
        """按 sessionid 取回当前可用浏览器；不存在/不可用返回 None。

        本地模式下兼作 keepalive 心跳（刷新空闲计时）。
        """
        if not self._ready:
            return None
        try:
            return await self.backend.get(sessionid)
        except Exception:  # noqa: BLE001
            logger.exception("get 失败 sessionid=%s", sessionid)
            return None

    async def destroy(self, sessionid: str) -> dict:
        """销毁浏览器：本地终止进程，云端调用 FC DeleteSession；随后删库（幂等）。"""
        if not self._ready:
            return self._err(ERR_NOT_READY, sessionid, "管理器未初始化")
        try:
            return await self.backend.destroy(sessionid)
        except Exception as e:  # noqa: BLE001
            logger.exception("destroy 失败 sessionid=%s", sessionid)
            return self._err(ERR_BACKEND, sessionid, f"销毁浏览器失败: {e}")

    # ------------------------------------------------------------------
    # 收尾 / 测试辅助
    # ------------------------------------------------------------------
    async def aclose(self) -> None:
        """停止后台任务（本地 reaper）。进程退出前调用。"""
        if self.backend is not None and hasattr(self.backend, "stop_reaper"):
            await self.backend.stop_reaper()

    @classmethod
    async def _reset_for_test(cls) -> None:
        """仅测试用：停后台任务并清空单例，便于不同环境重新初始化。"""
        if cls._instance is not None:
            try:
                await cls._instance.aclose()
            except Exception:  # noqa: BLE001
                pass
        cls._instance = None
        # 重建锁，避免跨事件循环复用（不同测试各自独立事件循环）
        cls._lock = asyncio.Lock()

    def _err(self, code: int, sessionid: str, msg: str) -> dict:
        return {
            "ok": False, "code": code, "sessionid": sessionid, "ws_url": "",
            "headers": {}, "mode": self.mode, "pid": 0, "msg": msg,
        }
