"""云函数浏览器后端（无状态：Vercel 等 Serverless 平台下使用）。

对接自建的 cloakbrowser-serverless（见 ``aliyunFC/cloakbrowser``）：以 sessionID 头
域亲和把同一会话路由到同一 FC 实例，浏览器由 ``GET /start`` 懒启动。由于部署为
``authType=function``（AK 签名鉴权），对函数 URL（``*.fcapp.run``）的每个请求都需
用 ``browser.signer`` 签名。

无状态约束（Serverless）：不持有任何跨请求内存状态，也不起后台任务。权威状态只在
**DB + FC**：
- 复用/校验：查 DB 记录 + 签名探测 ``GET /json/version``（浏览器确实在服务才算可用）；
- 创建：签名 ``GET /start`` 懒启动并等就绪，落库；
- 销毁：调用 FC OpenAPI ``DeleteSession``（SDK 自动签名），删库；
- 超时回收：交给 FC 服务端（session idle/ttl）+ 本类在 acquire/get 时懒清理过期记录。

返回结构与本地后端对齐：
``{"ok","code","sessionid","ws_url","headers","mode","pid","msg"}``。其中 ``headers``
为 WS 握手所需的**签名头**（sessionID 亲和头 + Date + Authorization），调用方以
``connect_over_cdp(ws_url, headers=headers)`` 直连——传入 ws 链接会跳过 Playwright 的
``/json/version`` 自动发现，故一次连接只需对根路径 ``/`` 签一次名。签名头具时效性
（Date 偏移窗口约 15 分钟），重连请调用 ``signed_ws_headers`` 重新获取。
"""

from __future__ import annotations

import asyncio
import base64
import hashlib
import json
import logging
import time
import urllib.error
import urllib.request
from typing import Any, Optional
from urllib.parse import urlsplit

from . import signer
from .local import _decode_meta, _encode_meta  # 复用运行态 base64(JSON) 编解码
from .local import _proxy_server, _region_identity  # 复用纯函数（无副作用）

logger = logging.getLogger("browser.cloud")

OK = 0
ERR_CLOUD_NOT_CONFIGURED = 3101  # 云端配置缺失（URL / AK / 函数名）
ERR_CLOUD_START_FAILED = 3102    # /start 懒启动失败或超时
ERR_CLOUD_AUTH = 3103            # 函数 URL 签名鉴权失败（401/403）


class BrowserCloudError(Exception):
    """云端浏览器操作失败（附带结果码，便于上层转 dict）。"""

    def __init__(self, message: str, code: int = ERR_CLOUD_START_FAILED):
        super().__init__(message)
        self.code = code
        self.msg = message


def fc_session_key(sessionid: str) -> str:
    """业务 sessionid -> FC 头域亲和会话 ID（sha256 hex，64 字符，恒满足字符集）。"""
    return hashlib.sha256(sessionid.encode("utf-8")).hexdigest()


def _encode_cfg_header(cfg: dict) -> str:
    """浏览器配置 dict -> X-Browser-Cfg（base64url(JSON)，键排序保证同配置稳定）。"""
    raw = json.dumps(cfg, ensure_ascii=False, sort_keys=True).encode("utf-8")
    return base64.urlsafe_b64encode(raw).decode("ascii")


def _browser_cfg(fp: dict) -> dict:
    """把上层指纹参数归一为 cloakbrowser 配置（seed/timezone/locale/proxy/extra_args）。"""
    fp = fp or {}
    cfg: dict[str, Any] = {}
    seed = fp.get("seed")
    if seed is not None:
        cfg["seed"] = str(seed)
    locale = fp.get("locale")
    timezone = fp.get("timezone")
    region = fp.get("region")
    if region and (not locale or not timezone):
        try:
            r_locale, r_tz = _region_identity(region)
            locale = locale or r_locale
            timezone = timezone or r_tz
        except Exception:  # noqa: BLE001 - 未知地区忽略，交由显式 locale/timezone
            pass
    if locale:
        cfg["locale"] = locale
    if timezone:
        cfg["timezone"] = timezone
    proxy = fp.get("proxy")
    if proxy:
        try:
            ps = _proxy_server(proxy)
            if ps:
                cfg["proxy"] = ps
        except Exception:  # noqa: BLE001
            pass
    extra = fp.get("extra_args")
    if extra:
        cfg["extra_args"] = list(extra)
    return cfg


class CloudBackend:
    """无状态云函数浏览器后端。"""

    mode = "cloud"

    def __init__(
        self,
        *,
        function_url: str,
        function_name: str,
        region: str,
        access_key_id: str,
        access_key_secret: str,
        account_id: str = "",
        affinity_header: str = "sessionid",
        qualifier: str = "LATEST",
        security_token: Optional[str] = None,
        start_timeout: float = 180.0,
    ) -> None:
        self.function_url = (function_url or "").rstrip("/")
        self.function_name = function_name or ""
        self.region = region or ""
        self.ak = access_key_id or ""
        self.sk = access_key_secret or ""
        self._account = account_id or ""
        self.affinity_header = affinity_header or "sessionid"
        self.qualifier = qualifier or "LATEST"
        self.security_token = security_token or None
        self.start_timeout = float(start_timeout or 180.0)
        self.ws_root = self._compute_ws_root(self.function_url)

    @staticmethod
    def _compute_ws_root(function_url: str) -> str:
        if not function_url:
            return ""
        p = urlsplit(function_url)
        scheme = "wss" if p.scheme == "https" else "ws"
        return f"{scheme}://{p.netloc}/"

    @property
    def configured(self) -> bool:
        return bool(self.function_url and self.function_name and self.ak and self.sk)

    def _not_configured(self, sessionid: str) -> dict:
        return {
            "ok": False, "code": ERR_CLOUD_NOT_CONFIGURED, "sessionid": sessionid,
            "ws_url": "", "headers": {}, "mode": "cloud", "pid": 0,
            "msg": "云端未配置：请在系统设置填写 fc_function_url / function_name / "
                   "platform_access_key_id / platform_access_key_secret",
        }

    # ------------------------------------------------------------------
    # 签名头
    # ------------------------------------------------------------------
    def signed_ws_headers(self, sessionid: str) -> dict:
        """生成 WS 握手所需签名头（对根路径 / 按 GET 签名 + 亲和头）。可用于重连重签。"""
        fk = fc_session_key(sessionid)
        return self._signed_headers("GET", self.ws_root, {self.affinity_header: fk})

    def _signed_headers(self, method: str, url: str, extra: dict) -> dict:
        return signer.sign_headers(
            method=method,
            url=url,
            access_key_id=self.ak,
            access_key_secret=self.sk,
            extra_headers=extra,
            security_token=self.security_token,
        )

    def _result(self, sessionid: str, fk: str, msg: str) -> dict:
        return {
            "ok": True, "code": OK, "sessionid": sessionid,
            "ws_url": self.ws_root,
            "headers": self._signed_headers("GET", self.ws_root, {self.affinity_header: fk}),
            "mode": "cloud", "pid": 0, "fc_session_key": fk, "msg": msg,
        }

    # ------------------------------------------------------------------
    # 同步 HTTP / FC OpenAPI（放线程池执行，避免阻塞事件循环）
    # ------------------------------------------------------------------
    def _http_get_signed(self, path: str, extra: dict, timeout: float):
        url = self.function_url + path
        headers = self._signed_headers("GET", url, extra)
        req = urllib.request.Request(url, headers=headers, method="GET")
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            status = getattr(resp, "status", resp.getcode())
            body = resp.read().decode("utf-8", errors="replace")
        try:
            data = json.loads(body)
        except ValueError:
            data = {"_raw": body}
        return status, data

    def _start_sync(self, fk: str, cfg_header: str) -> dict:
        """签名 GET /start 懒启动，轮询直到 ready；处理 409/503 重试、401/403 直接失败。"""
        path = "/start"
        extra = {self.affinity_header: fk, "X-Browser-Cfg": cfg_header}
        deadline = time.monotonic() + self.start_timeout
        delay = 1.0
        last = "无响应"
        while True:
            try:
                status, data = self._http_get_signed(
                    path, extra, timeout=min(30.0, self.start_timeout)
                )
                if isinstance(data, dict) and data.get("status") == "ready":
                    return data
                last = f"status={status} body={data}"
            except urllib.error.HTTPError as e:  # noqa: PERF203
                detail = ""
                try:
                    detail = e.read().decode("utf-8", errors="replace")
                except Exception:  # noqa: BLE001
                    pass
                if e.code in (401, 403):
                    raise BrowserCloudError(
                        f"函数 URL 签名鉴权失败(HTTP {e.code})：请确认平台 AK/SK 正确、"
                        f"且触发器 authType=function。{detail}",
                        ERR_CLOUD_AUTH,
                    )
                if e.code not in (409, 503):
                    raise BrowserCloudError(f"/start 失败 HTTP {e.code}: {detail}")
                last = f"HTTP {e.code}: {detail}"
            except (urllib.error.URLError, TimeoutError, OSError) as e:
                last = f"{type(e).__name__}: {e}"
            if time.monotonic() >= deadline:
                raise BrowserCloudError(
                    f"/start 未就绪（超时 {self.start_timeout}s）：{last}",
                    ERR_CLOUD_START_FAILED,
                )
            time.sleep(delay)
            delay = min(delay * 1.5, 5.0)

    def _json_version_ok(self, fk: str) -> bool:
        """签名探测 /json/version：浏览器确实在服务（返回 webSocketDebuggerUrl）才算可用。"""
        try:
            status, data = self._http_get_signed(
                "/json/version", {self.affinity_header: fk}, timeout=10.0
            )
            return status == 200 and isinstance(data, dict) and bool(
                data.get("webSocketDebuggerUrl")
            )
        except Exception:  # noqa: BLE001 - 任何异常都视为不可用
            return False

    def _fc_client(self):
        from alibabacloud_fc20230330.client import Client as FCClient
        from alibabacloud_tea_openapi.models import Config

        endpoint = f"{self._resolve_account_id()}.{self.region}.fc.aliyuncs.com"
        return FCClient(Config(
            access_key_id=self.ak,
            access_key_secret=self.sk,
            security_token=self.security_token,
            endpoint=endpoint,
            # 海外网络(如 Vercel)到大陆链路延迟高，放宽连接/读取超时。
            connect_timeout=10000, read_timeout=30000,
        ))

    def _resolve_account_id(self) -> str:
        """FC 3.0 endpoint 需账号 ID；配置缺省时用平台 AK 经 STS GetCallerIdentity 解析。"""
        if self._account:
            return self._account
        from alibabacloud_sts20150401.client import Client as StsClient
        from alibabacloud_tea_openapi.models import Config

        sts = StsClient(Config(
            access_key_id=self.ak,
            access_key_secret=self.sk,
            security_token=self.security_token,
            endpoint="sts.aliyuncs.com",
            connect_timeout=10000, read_timeout=30000,
        ))
        resp = sts.get_caller_identity()
        self._account = getattr(resp.body, "account_id", "") or ""
        if not self._account:
            raise BrowserCloudError("无法解析账号 ID（STS GetCallerIdentity 返回空）",
                                    ERR_CLOUD_NOT_CONFIGURED)
        return self._account

    def _delete_session_safe(self, fk: str) -> bool:
        from alibabacloud_fc20230330 import models as fc_models

        try:
            self._fc_client().delete_session(
                self.function_name, fk,
                fc_models.DeleteSessionRequest(qualifier=self.qualifier),
            )
            return True
        except Exception as e:  # noqa: BLE001 - 会话可能已过期/不存在，销毁应幂等
            logger.info("DeleteSession 忽略错误（可能已不存在）: %s", e)
            return False

    # ------------------------------------------------------------------
    # 主要能力（异步）
    # ------------------------------------------------------------------
    async def try_reuse(self, sessionid: str) -> Optional[dict]:
        from core.db import BrowserInstanceDB

        rec = await BrowserInstanceDB.get(sessionid)
        if not rec:
            return None
        fk = fc_session_key(sessionid)
        if await asyncio.to_thread(self._json_version_ok, fk):
            return self._result(sessionid, fk, "复用现有云端会话")
        # 不可用：终止会话并删库，交由上层重建
        await asyncio.to_thread(self._delete_session_safe, fk)
        await BrowserInstanceDB.delete(sessionid)
        return None

    async def create(self, sessionid: str, fp: dict) -> dict:
        if not self.configured:
            return self._not_configured(sessionid)
        from core.db import BrowserInstanceDB

        fk = fc_session_key(sessionid)
        cfg = _browser_cfg(fp)
        cfg_header = _encode_cfg_header(cfg)
        try:
            await asyncio.to_thread(self._start_sync, fk, cfg_header)
        except BrowserCloudError as e:
            return {
                "ok": False, "code": e.code, "sessionid": sessionid, "ws_url": "",
                "headers": {}, "mode": "cloud", "pid": 0, "msg": e.msg,
            }
        meta = {
            "mode": "cloud", "fp": cfg, "fc_session_key": fk,
            "created_ts": time.time(), "last_used": time.time(),
        }
        # 并发同 sessionid：主键唯一约束保证只落一行；冲突时浏览器已由 /start 复用，
        # 同一 fk 直接返回结果即可（幂等）。
        await BrowserInstanceDB.create(sessionid, cfg=_encode_meta(meta), pid=0)
        return self._result(sessionid, fk, "云端浏览器已就绪")

    async def get(self, sessionid: str) -> Optional[dict]:
        if not self.configured:
            return None
        return await self.try_reuse(sessionid)

    async def destroy(self, sessionid: str) -> dict:
        from core.db import BrowserInstanceDB

        if not self.configured:
            await BrowserInstanceDB.delete(sessionid)
            return {"ok": True, "code": OK, "sessionid": sessionid,
                    "mode": "cloud", "msg": "云端未配置，仅清理本地记录"}
        fk = fc_session_key(sessionid)
        ok = await asyncio.to_thread(self._delete_session_safe, fk)
        await BrowserInstanceDB.delete(sessionid)
        return {
            "ok": True, "code": OK, "sessionid": sessionid, "mode": "cloud",
            "msg": "云端会话已终止" if ok else "云端会话删除已提交（可能已不存在）",
        }
