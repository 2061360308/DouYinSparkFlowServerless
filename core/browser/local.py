"""本地浏览器进程管理（CloakBrowser / Chromium）。

以**独立 OS 进程**方式启动 cloakbrowser 的 chrome 二进制，开启 Chrome
DevTools 远程调试（CDP），供上层通过 ws 调试地址（如 Playwright
``connect_over_cdp``）连接控制。

设计要点：
- 直接 ``subprocess.Popen`` 拉起 chrome 二进制，不依赖 cloakbrowser 的
  Python 包装层 → 浏览器进程独立于调用方，pid 可控、可 stop。
- 通过 ``--remote-debugging-port=0`` + ``user-data-dir/DevToolsActivePort``
  自动获取空闲调试端口与 browser ws 地址（Chrome 默认输出 ``ws://``，
  若需 ``wss`` 请由外部反代 TLS 后自行替换 scheme）。
- 内置 ``--no-sandbox`` 等参数：普通用户（无 root）与容器环境可直接运行。
- 支持指纹 seed、地区（locale/timezone）、代理、伪装 Windows 平台。
"""

from __future__ import annotations

import argparse
import asyncio
import base64
import json
import logging
import os
import shutil
import signal
import subprocess
import tempfile
import time
import urllib.request
from pathlib import Path
from typing import Any, Optional, Union

logger = logging.getLogger("browser.local")

# ---------------------------------------------------------------------------
# 结果码（与 db 包风格保持一致：ok + code + msg）
# ---------------------------------------------------------------------------
OK = 0
ERR_BINARY_NOT_FOUND = 2001
ERR_LAUNCH_FAILED = 2002
ERR_TIMEOUT = 2003
ERR_INVALID_ARG = 2004
ERR_NOT_RUNNING = 2005

# 伪装平台：CloakBrowser 在 Linux 上默认即为 windows，这里显式声明
DEFAULT_PLATFORM = "windows"
SUPPORTED_PLATFORMS = ("windows", "macos")

# 无 root / 容器环境基础参数 + 常规自动化静默参数
STEALTH_ARGS = [
    "--no-sandbox",              # 无 root 权限时必须关闭 SUID sandbox
    "--disable-setuid-sandbox",
    "--disable-dev-shm-usage",   # 容器 /dev/shm 过小兜底
    "--no-first-run",
    "--disable-default-apps",
    "--disable-background-networking",
    "--disable-component-update",
    "--disable-sync",
    "--metrics-recording-only",
]

# 常见地区 -> (locale, IANA timezone)，用于 --fingerprint-locale/timezone
_REGION_DEFAULTS: dict[str, tuple[str, str]] = {
    "US": ("en-US", "America/New_York"),
    "GB": ("en-GB", "Europe/London"),
    "CA": ("en-CA", "America/Toronto"),
    "AU": ("en-AU", "Australia/Sydney"),
    "NZ": ("en-NZ", "Pacific/Auckland"),
    "JP": ("ja-JP", "Asia/Tokyo"),
    "KR": ("ko-KR", "Asia/Seoul"),
    "CN": ("zh-CN", "Asia/Shanghai"),
    "HK": ("zh-HK", "Asia/Hong_Kong"),
    "TW": ("zh-TW", "Asia/Taipei"),
    "SG": ("en-SG", "Asia/Singapore"),
    "IN": ("en-IN", "Asia/Kolkata"),
    "ID": ("id-ID", "Asia/Jakarta"),
    "TH": ("th-TH", "Asia/Bangkok"),
    "VN": ("vi-VN", "Asia/Ho_Chi_Minh"),
    "MY": ("en-MY", "Asia/Kuala_Lumpur"),
    "PH": ("en-PH", "Asia/Manila"),
    "DE": ("de-DE", "Europe/Berlin"),
    "FR": ("fr-FR", "Europe/Paris"),
    "IT": ("it-IT", "Europe/Rome"),
    "ES": ("es-ES", "Europe/Madrid"),
    "PT": ("pt-PT", "Europe/Lisbon"),
    "NL": ("nl-NL", "Europe/Amsterdam"),
    "BE": ("nl-BE", "Europe/Brussels"),
    "CH": ("de-CH", "Europe/Zurich"),
    "AT": ("de-AT", "Europe/Vienna"),
    "SE": ("sv-SE", "Europe/Stockholm"),
    "NO": ("nb-NO", "Europe/Oslo"),
    "DK": ("da-DK", "Europe/Copenhagen"),
    "FI": ("fi-FI", "Europe/Helsinki"),
    "PL": ("pl-PL", "Europe/Warsaw"),
    "CZ": ("cs-CZ", "Europe/Prague"),
    "RU": ("ru-RU", "Europe/Moscow"),
    "UA": ("uk-UA", "Europe/Kyiv"),
    "TR": ("tr-TR", "Europe/Istanbul"),
    "BR": ("pt-BR", "America/Sao_Paulo"),
    "MX": ("es-MX", "America/Mexico_City"),
    "AR": ("es-AR", "America/Argentina/Buenos_Aires"),
    "CL": ("es-CL", "America/Santiago"),
    "CO": ("es-CO", "America/Bogota"),
    "ZA": ("en-ZA", "Africa/Johannesburg"),
    "EG": ("ar-EG", "Africa/Cairo"),
    "SA": ("ar-SA", "Asia/Riyadh"),
    "AE": ("ar-AE", "Asia/Dubai"),
    "IL": ("he-IL", "Asia/Jerusalem"),
}


class BrowserError(Exception):
    """浏览器操作失败（附带结果码，便于上层转换为统一 dict）。"""

    def __init__(self, message: str, code: int = ERR_LAUNCH_FAILED):
        super().__init__(message)
        self.code = code
        self.msg = message


def _error(code: int, msg: str) -> dict:
    return {"ok": False, "code": code, "msg": msg}


# ---------------------------------------------------------------------------
# 二进制定位
# ---------------------------------------------------------------------------
def find_binary(binary: Union[str, Path, None] = None) -> Path:
    """定位 chrome 可执行文件：参数 > 环境变量 > 仓库默认位置。"""
    candidates: list[Path] = []
    if binary:
        candidates.append(Path(binary))
    env = os.environ.get("CLOAKBROWSER_BINARY_PATH")
    if env:
        candidates.append(Path(env))
    # browser/ 的上一级（仓库根）下的 cloakbrowser/chrome
    candidates.append(Path(__file__).resolve().parent.parent / "cloakbrowser" / "chrome")

    for c in candidates:
        if c.is_file():
            if not os.access(c, os.X_OK):
                try:
                    c.chmod(c.stat().st_mode | 0o111)
                except OSError:
                    continue
            return c
    raise BrowserError(
        "未找到 chrome 二进制，请通过 binary 参数或环境变量 "
        f"CLOAKBROWSER_BINARY_PATH 指定（已尝试: {[str(c) for c in candidates]}）",
        ERR_BINARY_NOT_FOUND,
    )


# ---------------------------------------------------------------------------
# 地区/代理参数解析
# ---------------------------------------------------------------------------
def _region_identity(region: str) -> tuple[Optional[str], Optional[str]]:
    """region（如 "US"/"JP"/"zh-CN"）→ (locale, timezone)，均可为空。"""
    r = region.strip()
    upper = r.upper()
    if upper in _REGION_DEFAULTS:
        return _REGION_DEFAULTS[upper]
    if "-" in r:  # 形如 "zh-CN"，直接作为 locale；时区需调用方显式给出
        return (r, None)
    raise BrowserError(
        f"未知地区 {region!r}，请直接传 locale/timezone 参数或补充映射",
        ERR_INVALID_ARG,
    )


def _proxy_server(proxy: Union[str, dict, None]) -> Optional[str]:
    """代理参数归一为 chrome 可用的 --proxy-server 值（http/socks5 均可）。"""
    if not proxy:
        return None
    if isinstance(proxy, str):
        return proxy
    server = proxy.get("server")
    if not server:
        raise BrowserError("proxy 字典缺少 server 字段", ERR_INVALID_ARG)
    scheme_host = server if "://" in server else f"http://{server}"
    user, pwd = proxy.get("username"), proxy.get("password")
    if user or pwd:
        from urllib.parse import quote

        sep = scheme_host.index("://") + 3
        scheme_host = (
            f"{scheme_host[:sep]}{quote(user or '')}:{quote(pwd or '')}@"
            f"{scheme_host[sep:]}"
        )
    return scheme_host


# ---------------------------------------------------------------------------
# 启动
# ---------------------------------------------------------------------------
def launch(
    *,
    seed: Union[int, str, None] = None,
    region: Optional[str] = None,
    locale: Optional[str] = None,
    timezone: Optional[str] = None,
    proxy: Union[str, dict, None] = None,
    platform: str = DEFAULT_PLATFORM,
    headless: bool = False,
    port: int = 0,
    host: str = "127.0.0.1",
    binary: Union[str, Path, None] = None,
    user_data_dir: Union[str, Path, None] = None,
    extra_args: Optional[list[str]] = None,
    wait_timeout: float = 30.0,
    keep_alive: bool = False,
) -> dict:
    """以独立进程启动 CloakBrowser，返回进程信息与 CDP ws 调试地址。

    参数：
        seed: 指纹 seed。相同 seed 跨启动得到一致指纹（不传则由二进制自定）。
        region: 地区码（如 "US"/"JP"/"zh-CN"），自动推导 locale + timezone。
        locale: IANA 语言标签（如 "en-US"），显式指定时优先于 region。
        timezone: IANA 时区（如 "America/New_York"），显式指定时优先于 region。
        proxy: 代理，如 "http://user:pass@host:8080" 或
               {"server": ..., "username": ..., "password": ...}（http/socks5）。
        platform: 伪装平台，默认 "windows"。
        headless: True 时以无头模式启动（默认有头，需 DISPLAY 环境）。
        port: 调试端口，0 表示让 chrome 自动挑选空闲端口（推荐）。
        host: 调试服务绑定地址，默认仅本机 127.0.0.1。
        binary: chrome 二进制路径，缺省自动定位。
        user_data_dir: 用户数据目录，缺省创建临时目录；stop 时可随 cleanup 删除。
        extra_args: 额外透传给 chrome 的命令行参数。
        wait_timeout: 等待调试端口就绪的最大秒数。
        keep_alive: True 时子进程 detach（自行管理），返回后父进程退出不杀掉浏览器。

    返回：{"ok": True, "code": OK, "pid": ..., "port": ..., "ws_url": ...,
          "user_data_dir": ..., "log_path": ..., "msg": ...}
    """
    bin_path = find_binary(binary)

    if platform not in SUPPORTED_PLATFORMS:
        raise BrowserError(
            f"不支持的 platform {platform!r}，可选 {SUPPORTED_PLATFORMS}", ERR_INVALID_ARG
        )

    # 地区解析：显式 locale/timezone 优先于 region 推导
    if region:
        r_locale, r_tz = _region_identity(region)
        locale = locale or r_locale
        timezone = timezone or r_tz

    # 用户数据目录
    own_dir = user_data_dir is None
    udir = Path(user_data_dir) if user_data_dir else Path(
        tempfile.mkdtemp(prefix="cloakbrowser-")
    )
    udir.mkdir(parents=True, exist_ok=True)
    log_path = udir / "chrome.log"

    # 组装 chrome 参数
    chrome_args: list[str] = [str(bin_path), *STEALTH_ARGS]
    if port:
        chrome_args.append(f"--remote-debugging-port={port}")
        if host != "127.0.0.1":
            chrome_args.append(f"--remote-debugging-address={host}")
    else:
        chrome_args.append("--remote-debugging-port=0")
    chrome_args.append(f"--user-data-dir={udir}")
    if seed is not None:
        chrome_args.append(f"--fingerprint={seed}")
    chrome_args.append(f"--fingerprint-platform={platform}")
    if locale:
        chrome_args.append(f"--fingerprint-locale={locale}")
        chrome_args.append(f"--lang={locale}")
    if timezone:
        chrome_args.append(f"--fingerprint-timezone={timezone}")
    proxy_server = _proxy_server(proxy)
    if proxy_server:
        chrome_args.append(f"--proxy-server={proxy_server}")
    if headless:
        chrome_args.append("--headless=new")
    if extra_args:
        chrome_args.extend(extra_args)
    chrome_args.append("about:blank")

    # 独立进程 + 独立进程组启动，便于 stop 时整组回收
    popen_kwargs: dict[str, Any] = dict(
        stdout=open(log_path, "wb"),
        stderr=subprocess.STDOUT,
        start_new_session=not keep_alive,
    )
    try:
        proc = subprocess.Popen(chrome_args, **popen_kwargs)
    except Exception as e:  # noqa: BLE001
        raise BrowserError(f"启动 chrome 失败: {e}", ERR_LAUNCH_FAILED) from e

    pid = proc.pid
    active_port_file = udir / "DevToolsActivePort"

    # 等待调试端口就绪（DevToolsActivePort: 第一行端口，第二行 ws 路径）
    deadline = time.monotonic() + wait_timeout
    while time.monotonic() < deadline:
        if proc.poll() is not None:
            tail = _tail(log_path)
            raise BrowserError(
                f"chrome 进程提前退出(exit={proc.returncode})\n{tail}",
                ERR_LAUNCH_FAILED,
            )
        if active_port_file.is_file():
            break
        time.sleep(0.2)
    else:
        stop(pid, cleanup_dir=udir if own_dir else None, timeout=3.0)
        raise BrowserError(
            f"等待调试端口超时({wait_timeout}s)：{_tail(log_path)}", ERR_TIMEOUT
        )

    try:
        port_line, path_line = active_port_file.read_text().strip().splitlines()
        debug_port = int(port_line.strip())
        ws_path = path_line.strip()
    except (ValueError, OSError) as e:
        stop(pid, cleanup_dir=udir if own_dir else None, timeout=3.0)
        raise BrowserError(f"解析 DevToolsActivePort 失败: {e}", ERR_LAUNCH_FAILED) from e

    ws_url = f"ws://{host}:{debug_port}{ws_path}"
    return {
        "ok": True,
        "code": OK,
        "pid": pid,
        "port": debug_port,
        "ws_url": ws_url,
        "debug_host": host,
        "user_data_dir": str(udir),
        "log_path": str(log_path),
        "headless": headless,
        "platform": platform,
        "msg": "浏览器已启动",
    }


# ---------------------------------------------------------------------------
# 停止 / 存活检查
# ---------------------------------------------------------------------------
def _pid_alive(pid: int) -> bool:
    """pid 进程是否存活（僵尸进程视为已死）。"""
    try:
        os.kill(pid, 0)
    except ProcessLookupError:
        return False
    except PermissionError:
        return True
    # 僵尸进程（state=Z）无法被信号影响，视为不存活
    try:
        with open(f"/proc/{pid}/stat", "rb") as f:
            data = f.read()
        rp = data.rfind(b")")
        if rp >= 0:
            state = data[rp + 1:].lstrip()[:1]
            if state == b"Z":
                return False
    except OSError:
        pass
    return True


def _children_of(pid: int) -> list[int]:
    """读取 /proc 找出 pid 的直接子进程（linux）。"""
    kids: list[int] = []
    try:
        for ent in os.listdir("/proc"):
            if not ent.isdigit():
                continue
            try:
                with open(f"/proc/{ent}/stat", "rb") as f:
                    data = f.read()
            except OSError:
                continue
            # stat 形如: pid (comm) state ppid ...（comm 可能含空格/括号，从右找 ')'）
            rp = data.rfind(b")")
            if rp < 0:
                continue
            fields = data[rp + 2:].split()
            if len(fields) >= 2 and fields[1].isdigit() and int(fields[1]) == pid:
                kids.append(int(ent))
    except OSError:
        pass
    return kids


def _process_tree(pid: int) -> list[int]:
    tree: list[int] = [pid]
    frontier = [pid]
    while frontier:
        nxt: list[int] = []
        for p in frontier:
            for c in _children_of(p):
                if c not in tree:
                    tree.append(c)
                    nxt.append(c)
        frontier = nxt
    return sorted(tree, reverse=True)


def stop(
    pid: int,
    *,
    cleanup_dir: Union[str, Path, None] = None,
    timeout: float = 6.0,
) -> dict:
    """终止 pid 对应的整个浏览器进程树，可选清理 user-data-dir。

    Chrome 会派生多个子进程，这里对 pid 及其全部后代先 SIGTERM，
    超时未退再 SIGKILL（与 launch 的独立进程组双保险）。
    """
    detail: dict[str, Any] = {"pid": pid, "tree": [], "cleaned": False}
    if not _pid_alive(pid):
        msg = "进程不存在或已退出"
    else:
        tree = _process_tree(pid)
        detail["tree"] = tree
        for p in tree:
            try:
                os.kill(p, signal.SIGTERM)
            except ProcessLookupError:
                pass
        deadline = time.monotonic() + timeout
        while time.monotonic() < deadline and _pid_alive(pid):
            time.sleep(0.2)
        if _pid_alive(pid):
            for p in tree:
                try:
                    os.kill(p, signal.SIGKILL)
                except ProcessLookupError:
                    pass
        # 若 pid 是当前进程的直接子进程，回收避免残留僵尸
        try:
            os.waitpid(pid, os.WNOHANG)
        except ChildProcessError:
            pass
        msg = "浏览器已停止"
    if cleanup_dir:
        shutil.rmtree(cleanup_dir, ignore_errors=True)
        detail["cleaned"] = True
    return {"ok": True, "code": OK, "pid": pid, "msg": msg, "detail": detail}


def is_alive(pid: int) -> bool:
    """pid 对应的进程是否存活。"""
    return _pid_alive(pid)


def _tail(path: Path, n: int = 30) -> str:
    try:
        lines = path.read_text(errors="replace").splitlines()
        return "--- chrome.log 尾部 ---\n" + "\n".join(lines[-n:])
    except OSError:
        return ""


# ---------------------------------------------------------------------------
# 异步包装（供上层 asyncio 环境调用，避免阻塞事件循环）
# ---------------------------------------------------------------------------
async def launch_async(*args: Any, **kwargs: Any) -> dict:
    return await asyncio.to_thread(launch, *args, **kwargs)


async def stop_async(pid: int, **kwargs: Any) -> dict:
    return await asyncio.to_thread(stop, pid, **kwargs)


# ---------------------------------------------------------------------------
# 按 sessionid 组织的本地浏览器后端（有状态：仅服务器 docker 部署下使用）
# ---------------------------------------------------------------------------
# 与云函数后端接口对齐（acquire/get/destroy），但本地为长驻进程，可持久化管理
# chrome OS 进程，并通过后台 reaper 做空闲/TTL 超时自动回收。运行态（ws 地址、
# user_data_dir、端口、时间戳）以 base64(JSON) 存入 BrowserInstance.cfg，pid 存
# pid 列——从而“通过 sessionid 取回浏览器”，且进程重启后可重新认领/清理孤儿。
#
# 空闲判定（与云端 FC 语义对齐）：管理器不在 CDP 数据链路上（调用方直连 chrome
# debug 端口），无法观测真实流量，故通过解析 /proc/net/tcp(6) 判断“debug 端口是否
# 还有 CDP 客户端连接”——有连接则视为在用、绝不回收；断开约 idle 秒后回收；无论
# 是否连接，超过 TTL 一律回收（硬顶）。

# launch() 接受的启动/指纹参数白名单（过滤上层透传的其它键）
_LAUNCH_KEYS = frozenset({
    "seed", "region", "locale", "timezone", "proxy",
    "platform", "headless", "extra_args", "binary", "host",
})


def _encode_meta(meta: dict) -> str:
    """运行态 dict -> base64(JSON)（落入 BrowserInstance.cfg）。"""
    return base64.b64encode(
        json.dumps(meta, ensure_ascii=False).encode("utf-8")
    ).decode("ascii")


def _decode_meta(cfg: str) -> dict:
    """BrowserInstance.cfg -> 运行态 dict（解析失败返回空 dict）。"""
    try:
        return json.loads(base64.b64decode(cfg.encode("ascii")).decode("utf-8"))
    except Exception:  # noqa: BLE001
        return {}


def _cdp_ok(host: str, port: int, timeout: float = 1.5) -> bool:
    """探测本地 CDP /json/version 是否可用（校验浏览器是否真的还能用）。"""
    if not port:
        return False
    url = f"http://{host or '127.0.0.1'}:{int(port)}/json/version"
    try:
        with urllib.request.urlopen(url, timeout=timeout) as resp:
            data = json.load(resp)
        return bool(isinstance(data, dict) and data.get("webSocketDebuggerUrl"))
    except Exception:  # noqa: BLE001
        return False


# Linux /proc/net/tcp 连接状态码：01=ESTABLISHED，0A=LISTEN
_TCP_ESTABLISHED = "01"


def _parse_established_ports(proc_text: str) -> set[int]:
    """从 /proc/net/tcp(6) 文本解析出所有处于 ESTABLISHED 状态的本地端口。

    行格式（首行为表头）：``sl local_address rem_address st ...``，其中
    ``local_address`` 形如 ``0100007F:2382``（IP:PORT，端口为 4 位十六进制）。
    """
    ports: set[int] = set()
    for line in proc_text.splitlines()[1:]:  # 跳过表头
        fields = line.split()
        if len(fields) < 4:
            continue
        local_addr, state = fields[1], fields[3]
        if state != _TCP_ESTABLISHED:
            continue
        hexport = local_addr.rsplit(":", 1)[-1]
        try:
            ports.add(int(hexport, 16))
        except ValueError:
            continue
    return ports


def _has_cdp_client(port: int, host: str = "127.0.0.1") -> bool:
    """debug 端口上是否存在已建立的 CDP 客户端连接（判定“在用”）。

    读取 /proc/net/tcp 与 /proc/net/tcp6，取 ESTABLISHED 连接的本地端口集合。
    读取/解析失败时**保守返回 True**（宁可不回收，交由 TTL 硬顶兜底），避免误杀
    正在使用的会话。
    """
    if not port:
        return False
    port = int(port)
    ok_any = False
    for path in ("/proc/net/tcp", "/proc/net/tcp6"):
        try:
            with open(path, "r", encoding="ascii", errors="replace") as f:
                text = f.read()
        except OSError:
            continue
        ok_any = True
        if port in _parse_established_ports(text):
            return True
    if not ok_any:
        # 两个文件都读不到（非 Linux/受限环境）：无法判定，保守视为“在用”
        return True
    return False


class LocalBackend:
    """本地浏览器后端：按 sessionid 懒启动/复用/校验/销毁，并做超时自动回收。

    返回结构与云端对齐：
    ``{"ok","code","sessionid","ws_url","headers","mode","pid","msg"}``
    （本地 ``headers`` 恒为空 dict——本地 CDP 无需签名）。
    """

    mode = "local"

    def __init__(
        self,
        *,
        ttl_seconds: int = 600,
        idle_timeout_seconds: int = 30,
        reaper_interval: Optional[float] = None,
    ) -> None:
        self.ttl = max(0, int(ttl_seconds or 0))
        self.idle = max(0, int(idle_timeout_seconds or 0))
        # reaper 周期：取 idle/ttl 中较小值的一半，夹在 [5s, 60s]，缺省 15s
        base = min([v for v in (self.idle, self.ttl) if v] or [30])
        self.reaper_interval = float(reaper_interval or max(5.0, min(60.0, base / 2)))
        self._reaper_task: Optional[asyncio.Task] = None

    # ---- reaper 生命周期 ----
    async def start_reaper(self) -> None:
        if self._reaper_task is None or self._reaper_task.done():
            self._reaper_task = asyncio.create_task(self._reaper_loop())

    async def stop_reaper(self) -> None:
        if self._reaper_task is not None:
            self._reaper_task.cancel()
            try:
                await self._reaper_task
            except asyncio.CancelledError:
                pass
            self._reaper_task = None

    async def reconcile(self) -> None:
        """进程重启后清理 DB 中已死/超时的实例行（存活且未超时的进程予以保留）。"""
        await self._reap_once()

    # ---- 主要能力 ----
    async def try_reuse(self, sessionid: str) -> Optional[dict]:
        """存在且可用则复用并刷新 last_used；失效则清理并返回 None。"""
        from core.db import BrowserInstanceDB

        rec = await BrowserInstanceDB.get(sessionid)
        if not rec:
            return None
        meta = _decode_meta(rec["cfg"])
        pid = rec["pid"]
        alive = await asyncio.to_thread(is_alive, pid)
        if alive and await asyncio.to_thread(
            _cdp_ok, meta.get("debug_host", "127.0.0.1"), int(meta.get("port") or 0)
        ):
            meta["last_used"] = time.time()
            await BrowserInstanceDB.update(sessionid, cfg=_encode_meta(meta))
            return self._result(sessionid, meta.get("ws_url", ""), pid, "复用现有本地浏览器")
        await self._stop_and_delete(sessionid, pid, meta)
        return None

    async def create(self, sessionid: str, fp: dict) -> dict:
        """启动新浏览器并落库；写库冲突（并发同 sessionid）则回退复用既有。"""
        from core.db import BrowserInstanceDB

        launch_kwargs = {
            k: v for k, v in (fp or {}).items() if k in _LAUNCH_KEYS and v is not None
        }
        info = await launch_async(**launch_kwargs)
        pid = info["pid"]
        meta = {
            "mode": "local",
            "fp": launch_kwargs,
            "ws_url": info["ws_url"],
            "user_data_dir": info.get("user_data_dir"),
            "debug_host": info.get("debug_host", "127.0.0.1"),
            "port": info.get("port"),
            "created_ts": time.time(),
            "last_used": time.time(),
        }
        res = await BrowserInstanceDB.create(sessionid, cfg=_encode_meta(meta), pid=pid)
        if not res["ok"]:
            await stop_async(pid, cleanup_dir=meta.get("user_data_dir"))
            reused = await self.try_reuse(sessionid)
            if reused:
                return reused
            return {
                "ok": False, "code": ERR_LAUNCH_FAILED, "sessionid": sessionid,
                "ws_url": "", "headers": {}, "mode": "local", "pid": 0,
                "msg": "创建本地浏览器失败（写库冲突且无法复用）",
            }
        return self._result(sessionid, info["ws_url"], pid, "本地浏览器已就绪")

    async def get(self, sessionid: str) -> Optional[dict]:
        """按 sessionid 取回可用浏览器（兼作 keepalive 心跳，刷新 last_used）。"""
        return await self.try_reuse(sessionid)

    async def destroy(self, sessionid: str) -> dict:
        """终止本地浏览器进程并删除记录（幂等）。"""
        from core.db import BrowserInstanceDB

        rec = await BrowserInstanceDB.get(sessionid)
        if not rec:
            return {"ok": True, "code": OK, "sessionid": sessionid,
                    "mode": "local", "msg": "无对应实例"}
        meta = _decode_meta(rec["cfg"])
        await self._stop_and_delete(sessionid, rec["pid"], meta)
        return {"ok": True, "code": OK, "sessionid": sessionid,
                "mode": "local", "msg": "本地浏览器已销毁"}

    # ---- 内部 ----
    def _result(self, sessionid: str, ws_url: str, pid: int, msg: str) -> dict:
        return {
            "ok": True, "code": OK, "sessionid": sessionid, "ws_url": ws_url,
            "headers": {}, "mode": "local", "pid": pid, "msg": msg,
        }

    async def _stop_and_delete(self, sessionid: str, pid: int, meta: dict) -> None:
        from core.db import BrowserInstanceDB

        try:
            await stop_async(pid, cleanup_dir=meta.get("user_data_dir"))
        except Exception:  # noqa: BLE001
            logger.exception("停止本地浏览器进程失败 pid=%s", pid)
        await BrowserInstanceDB.delete(sessionid)

    async def _reaper_loop(self) -> None:
        while True:
            try:
                await asyncio.sleep(self.reaper_interval)
                await self._reap_once()
            except asyncio.CancelledError:
                break
            except Exception:  # noqa: BLE001
                logger.exception("本地浏览器 reaper 单轮异常（忽略，继续）")

    async def _reap_once(self) -> None:
        """扫描全部实例并按“连接感知空闲 + TTL 硬顶”回收。

        - 进程已死 → 回收；
        - 超过 TTL（最长生命周期）→ 回收（即使仍有客户端连接）；
        - 仍在 TTL 内：若 debug 端口尚有 CDP 客户端连接 → 视为在用，刷新 last_used
          保活、不回收；已无连接且距上次“在用/触碰”超过 idle 秒 → 回收。
        """
        from core.db import BrowserInstanceDB

        now = time.time()
        for rec in await BrowserInstanceDB.list_all():
            meta = _decode_meta(rec["cfg"])
            if meta.get("mode") != "local":
                continue
            sessionid = rec["sessionid"]
            pid = rec["pid"]
            created = float(meta.get("created_ts") or 0)

            dead = not await asyncio.to_thread(is_alive, pid)
            ttl_over = bool(self.ttl and now - created > self.ttl)
            if dead or ttl_over:
                await self._stop_and_delete(sessionid, pid, meta)
                continue

            # 仍存活且未到 TTL：按“是否还有客户端连接”判定空闲
            port = int(meta.get("port") or 0)
            host = meta.get("debug_host", "127.0.0.1")
            has_client = await asyncio.to_thread(_has_cdp_client, port, host)
            if has_client:
                # 保活：刷新 last_used，使断开后从此刻起算 idle 超时
                meta["last_used"] = now
                await BrowserInstanceDB.update(sessionid, cfg=_encode_meta(meta))
                continue

            last = float(meta.get("last_used") or created)
            if self.idle and now - last > self.idle:
                await self._stop_and_delete(sessionid, pid, meta)


# ---------------------------------------------------------------------------
# CLI：python -m core.browser.local launch/stop
# ---------------------------------------------------------------------------
def main(argv: Optional[list[str]] = None) -> None:
    parser = argparse.ArgumentParser(
        prog="python -m core.browser", description="本地 CloakBrowser 进程管理"
    )
    sub = parser.add_subparsers(dest="cmd", required=True)

    p_launch = sub.add_parser("launch", help="启动浏览器并输出进程信息")
    p_launch.add_argument("--seed", type=str, help="指纹 seed")
    p_launch.add_argument("--region", help='地区，如 "US" / "JP" / "zh-CN"')
    p_launch.add_argument("--locale", help="语言标签，如 en-US")
    p_launch.add_argument("--timezone", help="IANA 时区，如 Asia/Tokyo")
    p_launch.add_argument("--proxy", help="代理 URL")
    p_launch.add_argument("--platform", default=DEFAULT_PLATFORM)
    p_launch.add_argument("--headless", action="store_true")
    p_launch.add_argument("--port", type=int, default=0)
    p_launch.add_argument("--user-data-dir")
    p_launch.add_argument("--extra-args", nargs="*", default=None)

    p_stop = sub.add_parser("stop", help="停止浏览器进程")
    p_stop.add_argument("--pid", type=int, required=True)
    p_stop.add_argument("--cleanup-dir", help="随停止删除的用户数据目录")

    ns = parser.parse_args(argv)
    try:
        if ns.cmd == "launch":
            result = launch(
                seed=ns.seed,
                region=ns.region,
                locale=ns.locale,
                timezone=ns.timezone,
                proxy=ns.proxy,
                platform=ns.platform,
                headless=ns.headless,
                port=ns.port,
                user_data_dir=ns.user_data_dir,
                extra_args=ns.extra_args,
            )
        else:  # stop
            result = stop(ns.pid, cleanup_dir=ns.cleanup_dir)
    except BrowserError as e:
        result = _error(e.code, e.msg)
    print(json.dumps(result, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
