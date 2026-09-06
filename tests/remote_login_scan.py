"""通过远程 cloakbrowser 浏览器完成抖音扫码登录，落盘浏览器指纹 + 账号信息 + 出口 IP。

用法:
    python tests/remote_login_scan.py [BASE_URL] [--seed SEED] [--out-dir DIR]
        [--timeout 秒] [--probe-only]

每隔端点独立页面探测出口 IP（FC NAT 池可能返回多个出口 IP，全部记录）。
"""
from __future__ import annotations

import argparse
import asyncio
import base64
import hashlib
import json
import os
import queue
import re
import sys
import threading
import time
import urllib.error
import urllib.request
from datetime import datetime
from pathlib import Path
from urllib.parse import urlsplit


def _spark_root() -> Path:
    candidates = [
        Path(__file__).resolve().parent.parent / "tmpcode" / "DouYinSparkFlow",
        Path("/workspace/tmpcode/DouYinSparkFlow"),
    ]
    for candidate in candidates:
        if (candidate / "spark_console" / "auth_scanner.py").is_file():
            return candidate
    raise RuntimeError("未找到 spark 项目目录 (tmpcode/DouYinSparkFlow)")


_SPARK_ROOT = _spark_root()
if str(_SPARK_ROOT) not in sys.path:
    sys.path.insert(0, str(_SPARK_ROOT))

from spark_console.auth_scanner import (
    CONFIRMING_TEXT,
    VERIFICATION_TEXT,
    DouyinQrScanner,
    LoginTimedOut,
    QrLoadFailed,
    ScanCancelled,
    VerificationRequired,
)

SESSION_HEADER = "sessionID"
CFG_HEADER = "X-Browser-Cfg"
DEFAULT_BASE = "https://browser-test-nlbmudxesk.cn-hangzhou.fcapp.run"
DEFAULT_TZ = "Asia/Shanghai"
DEFAULT_LOCALE = "zh-CN"
DEFAULT_SEED = "dy-fixed-888888"
IP_PATTERN = re.compile(r"(?:\d{1,3}\.){3}\d{1,3}")
MAX_EGRESS_OBSERVATIONS = 4
IP_ENDPOINTS = (
    "https://myip.ipip.net",
    "https://api.ip.sb/ip",
    "https://cip.cc",
    "https://ipinfo.io/ip",
    "https://ifconfig.me/ip",
    "https://checkip.amazonaws.com",
)

FINGERPRINT_JS = """() => {
  const out = {};
  out.userAgent = navigator.userAgent || "";
  out.platform = navigator.platform || "";
  out.language = navigator.language || "";
  out.languages = Array.from(navigator.languages || []);
  out.hardwareConcurrency = navigator.hardwareConcurrency;
  out.deviceMemory = navigator.deviceMemory;
  out.maxTouchPoints = navigator.maxTouchPoints;
  out.vendor = navigator.vendor || "";
  out.webdriver = navigator.webdriver;
  out.screen = {
    width: screen.width, height: screen.height,
    availWidth: screen.availWidth, availHeight: screen.availHeight,
    colorDepth: screen.colorDepth, pixelDepth: screen.pixelDepth,
  };
  out.window = {
    innerWidth: window.innerWidth, innerHeight: window.innerHeight,
    outerWidth: window.outerWidth, outerHeight: window.outerHeight,
    devicePixelRatio: window.devicePixelRatio,
  };
  out.timezone = Intl.DateTimeFormat().resolvedOptions().timeZone || "";
  out.remoteTime = new Date().toString();
  try {
    const c = document.createElement("canvas");
    c.width = 240; c.height = 40;
    const ctx = c.getContext("2d");
    ctx.textBaseline = "top";
    ctx.font = "14px Arial";
    ctx.fillStyle = "#f60"; ctx.fillRect(0, 0, 240, 40);
    ctx.fillStyle = "#069"; ctx.fillText("cloakbrowser-fp-0123456789", 4, 18);
    out.canvasHash = c.toDataURL();
  } catch (e) { out.canvasHash = null; }
  out.webgl = { vendor: null, renderer: null, version: null, shaderVersion: null };
  try {
    const c = document.createElement("canvas");
    const gl = c.getContext("webgl") || c.getContext("experimental-webgl");
    if (gl) {
      const ext = gl.getExtension("WEBGL_debug_renderer_info");
      out.webgl = {
        vendor: ext ? gl.getParameter(ext.UNMASKED_VENDOR_WEBGL) : null,
        renderer: ext ? gl.getParameter(ext.UNMASKED_RENDERER_WEBGL) : null,
        version: gl.getParameter(gl.VERSION),
        shaderVersion: gl.getParameter(gl.SHADING_LANGUAGE_VERSION),
      };
    }
  } catch (e) {
    out.webgl = { vendor: null, renderer: null, version: null, shaderVersion: null };
  }
  return out;
}"""


class RemoteBrowserSession:
    def __init__(self, base: str, sid: str, cfg_b64: str) -> None:
        self.base = base.rstrip("/")
        self.sid = sid
        self.cfg_b64 = cfg_b64
        self.ws = derive_ws_url(self.base)
        self.browser_version = ""
        self.context_mode = "new-context"
        self._pw = None
        self._browser = None

    @property
    def chromium(self):
        return _ChromiumShim(self)

    async def __aenter__(self):
        return self

    async def __aexit__(self, exc_type, exc, tb):
        pw = self._pw
        self._pw = None
        if pw is not None:
            await pw.stop()
        return False

    async def _connect(self):
        from playwright.async_api import async_playwright

        self._pw = await async_playwright().start()
        try:
            real = await self._pw.chromium.connect_over_cdp(
                self.ws, headers={SESSION_HEADER: self.sid}, timeout=120_000
            )
        except BaseException:
            pw = self._pw
            self._pw = None
            if pw is not None:
                await pw.stop()
            raise
        self._browser = _DelegatingBrowser(real, self)
        return self._browser


class _ChromiumShim:
    def __init__(self, owner) -> None:
        self._owner = owner

    async def launch(self, **_kwargs):
        return await self._owner._connect()


class _DelegatingContext:
    def __init__(self, real_context) -> None:
        self._real = real_context

    def __getattr__(self, name):
        return getattr(self._real, name)

    async def close(self):
        return None


class _DelegatingBrowser:
    def __init__(self, real_browser, owner) -> None:
        object.__setattr__(self, "_real", real_browser)
        self._owner = owner

    def __getattr__(self, name):
        return getattr(self._real, name)

    async def new_context(self, *args, **kwargs):
        try:
            return await self._real.new_context(*args, **kwargs)
        except Exception as exc:
            self._owner.context_mode = "default-fallback"
            print(f"[info] new_context 不可用 ({exc})，改用默认 context")
            return _DelegatingContext(self._real.contexts[0])

    async def close(self):
        try:
            await self._real.close()
        except Exception:
            pass
        return None


class VerificationTolerantScanner(DouyinQrScanner):
    _prompted = False

    @staticmethod
    async def _wait_for_any_text(page, values):
        if any(value in VERIFICATION_TEXT for value in values):
            if not VerificationTolerantScanner._prompted:
                VerificationTolerantScanner._prompted = True
                print(
                    "\n[!] 检测到「安全验证 / 请完成验证」：\n"
                    "    查看 live_view.png 确认界面，然后在控制台输入短信验证码"
                    "（4-8 位数字，回车）；click 输入 `click x y`（0~1 归一化坐标）。\n"
                )
            await asyncio.Event().wait()
        return await DouyinQrScanner._wait_for_any_text(page, values)

    @staticmethod
    async def _account_session_is_authenticated(context) -> bool:
        try:
            pages = context.pages
            if not pages:
                return False
            return bool(
                await pages[0].evaluate(
                    """async () => {
                        try {
                          const resp = await fetch("/passport/account/info/v2/?aid=6383", {credentials: "include"});
                          if (!resp.ok) return false;
                          const data = await resp.json().catch(() => null);
                          if (!data || !data.data) return false;
                          return !!(data.message === "success" && data.data && !data.data.error_code && data.data.user_id);
                        } catch (e) { return false; }
                    }"""
                )
            )
        except Exception:
            return False


def build_session_id(cfg_with_seq: dict) -> str:
    raw = json.dumps(cfg_with_seq, ensure_ascii=False, sort_keys=True).encode("utf-8")
    return hashlib.sha256(raw).hexdigest()


def encode_cfg_header(base_cfg: dict) -> str:
    raw = json.dumps(base_cfg, ensure_ascii=False, sort_keys=True).encode("utf-8")
    return base64.urlsafe_b64encode(raw).decode("ascii")


def derive_ws_url(base: str) -> str:
    parts = urlsplit(base)
    scheme = "wss" if parts.scheme == "https" else "ws"
    return f"{scheme}://{parts.netloc}/"


def start_browser(base: str, sid: str, cfg_b64: str, timeout: float = 180.0) -> dict:
    req = urllib.request.Request(
        f"{base}/start",
        method="GET",
        headers={SESSION_HEADER: sid, CFG_HEADER: cfg_b64},
    )
    opener = urllib.request.build_opener(urllib.request.ProxyHandler({}))
    delay = 1.0
    last = "unknown"
    for _attempt in range(12):
        try:
            with opener.open(req, timeout=timeout) as resp:
                body = json.load(resp)
            if body.get("status") == "ready":
                return body
            last = f"status={body.get('status')} body={body}"
        except urllib.error.HTTPError as exc:
            detail = exc.read().decode("utf-8", "replace")[:200]
            last = f"HTTP {exc.code}: {detail}"
            if exc.code == 400:
                raise RuntimeError(f"GET /start 400: {detail}")
        except Exception as exc:
            last = f"{type(exc).__name__}: {exc}"
        time.sleep(delay)
        delay = min(delay * 2, 8.0)
    raise RuntimeError(f"远程浏览器启动失败: {last}")


async def probe_fingerprint(page) -> dict:
    try:
        return await page.evaluate(FINGERPRINT_JS)
    except Exception as exc:
        print(f"[warn] 指纹采集失败: {exc}")
        return {"error": str(exc)}


async def _probe_one_ip(context, url: str):
    page = await context.new_page()
    try:
        await page.goto(url, wait_until="domcontentloaded", timeout=20_000)
        await asyncio.sleep(0.5)
        text = await page.evaluate(
            "() => document.body ? document.body.innerText.slice(0, 300) : ''"
        )
        match = IP_PATTERN.search(text)
        if match:
            return {"ip": match.group(0), "source": url, "raw": text[:120]}
    except Exception:
        return None
    finally:
        try:
            await page.close()
        except Exception:
            pass
    return None


async def probe_egress_ips(context) -> dict:
    observations = []
    for url in IP_ENDPOINTS:
        if len(observations) >= MAX_EGRESS_OBSERVATIONS:
            break
        result = await _probe_one_ip(context, url)
        if result:
            observations.append(result)
    return {
        "primary": observations[0]["ip"] if observations else None,
        "observations": observations,
    }


def _open_stdin_reader(cmd_queue: queue.Queue) -> threading.Thread:
    def _reader():
        for line in sys.stdin:
            cmd_queue.put(line)

    thread = threading.Thread(target=_reader, daemon=True)
    thread.start()
    return thread


def _consume_cmd(
    cmd_queue: queue.Queue,
    cancel_event: threading.Event,
    viewport_size: dict | None = None,
):
    try:
        raw = cmd_queue.get_nowait()
    except queue.Empty:
        return None
    s = raw.strip()
    if not s:
        return None
    low = s.lower()
    if low in ("quit", "cancel", "q", "exit"):
        print("[提示] 收到取消指令，退出扫码等待...")
        cancel_event.set()
        return None
    parts = s.split(None, 1)
    cmd = parts[0].lower()
    arg = parts[1].strip() if len(parts) > 1 else ""
    if cmd in ("click", "点", "点击"):
        tokens = arg.split()
        if len(tokens) >= 2:
            try:
                return {"kind": "click", "x": float(tokens[0]), "y": float(tokens[1])}
            except ValueError:
                pass
        if arg:
            return {"kind": "click_text", "text": arg}
    if cmd in ("pixel", "像素"):
        tokens = arg.split()
        if len(tokens) >= 2:
            try:
                x = float(tokens[0])
                y = float(tokens[1])
            except ValueError:
                return None
            if viewport_size:
                width = float(viewport_size.get("width") or 1280)
                height = float(viewport_size.get("height") or 720)
                if width > 0 and height > 0:
                    return {"kind": "click", "x": x / width, "y": y / height}
    if cmd in ("sel", "选择器"):
        if arg:
            return {"kind": "click_sel", "selector": arg}
    if s.isdigit() and 4 <= len(s) <= 8:
        return {"kind": "text", "text": s}
    print(
        "[提示] 忽略输入：4-8 位数字=验证码 / 点 <按钮文本> / 选择器 <css选择器> / "
        "click x y(0~1比例) / pixel x y(整图像素) / quit"
    )
    return None


def _identity_dict(identity) -> dict:
    return {
        "sec_uid": identity.sec_uid,
        "short_id": identity.short_id,
        "unique_id": identity.unique_id,
        "nickname": identity.nickname,
        "remark_name": identity.remark_name,
    }


def _save_report(report: dict, out_dir: Path) -> None:
    target = out_dir / "account.json"
    target.write_text(
        json.dumps(report, ensure_ascii=False, indent=2, default=str), encoding="utf-8"
    )


async def run(
    base: str,
    seed: str,
    out_dir: Path,
    timeout_seconds: float,
    probe_only: bool,
) -> int:
    base_cfg = {
        "seed": seed,
        "timezone": DEFAULT_TZ,
        "locale": DEFAULT_LOCALE,
        "extra_args": ["--window-size=1280,800"],
    }
    seq = 0
    sid = build_session_id({**base_cfg, "seq": seq})
    cfg_b64 = encode_cfg_header(base_cfg)

    print(f"[1/6] 启动远程浏览器 {base}  seed={seed}")
    body = start_browser(base, sid, cfg_b64)
    ws = body.get("ws") or derive_ws_url(base)
    print(f"[2/6] 浏览器就绪 ws={ws}  browser={body.get('browser', '')}")

    instance = RemoteBrowserSession(base, sid, cfg_b64)
    instance.ws = ws
    instance.browser_version = body.get("browser", "")

    cancel_event = threading.Event()
    cmd_queue: queue.Queue = queue.Queue()
    viewport_state: dict = {"width": 1280, "height": 720}
    _open_stdin_reader(cmd_queue)

    def cancelled():
        return cancel_event.is_set()

    def next_interaction():
        return _consume_cmd(cmd_queue, cancel_event, viewport_state)

    def on_qr(full_png, crop_png=None):
        (out_dir / "qrcode_full.png").write_bytes(full_png)
        if crop_png:
            (out_dir / "qrcode_crop.png").write_bytes(crop_png)
        print(
            f"[扫码] 二维码已保存 -> {out_dir / 'qrcode_full.png'}"
            "（手机抖音扫一扫后在手机上确认）"
        )
        return None

    def on_confirming(_ok):
        print("[扫码] 二维码已被扫描/确认，正在等待登录状态落定...")

    def on_view(png):
        try:
            (out_dir / "live_view.png").write_bytes(png)
        except Exception:
            pass

    report = {
        "generated_at": datetime.now().isoformat(),
        "remote_browser": {
            "base_url": base,
            "ws_url": ws,
            "browser_version": body.get("browser", ""),
            "session_id": sid,
            "seq": seq,
        },
        "browser_fingerprint": {
            "requested_config": base_cfg,
            "observed": None,
        },
        "egress_ip": None,
        "account": None,
    }

    scanner = VerificationTolerantScanner(
        playwright_factory=lambda: instance,
        qr_timeout_seconds=90,
        login_timeout_seconds=timeout_seconds,
        poll_interval_seconds=0.3,
    )

    try:
        ensure_ok = await scanner.ensure_prepared(
            max_age_seconds=86400, cancelled=cancelled
        )
        if not ensure_ok or scanner._prepared is None:
            raise RuntimeError("远程浏览器内容未就绪")
        prepared = scanner._prepared
        try:
            viewport = await prepared.page.viewport_size()
        except Exception:
            viewport = None
        if viewport:
            viewport_state["width"] = viewport.get("width", 1280)
            viewport_state["height"] = viewport.get("height", 720)
        probe_page = await prepared.context.new_page()
        try:
            fingerprint = await probe_fingerprint(probe_page)
        finally:
            try:
                await probe_page.close()
            except Exception:
                pass
        egress = await probe_egress_ips(prepared.context)

        report["browser_fingerprint"]["observed"] = fingerprint
        report["egress_ip"] = egress
        report["remote_browser"]["context_mode"] = instance.context_mode

        print("[3/6] 浏览器指纹已采集")
        print(f"      UA: {fingerprint.get('userAgent')}")
        print(f"      canvas: {str(fingerprint.get('canvasHash', ''))[:60]}...")
        print(
            f"      webgl renderer: {(fingerprint.get('webgl') or {}).get('renderer')}"
        )
        print(
            f"      timezone: {fingerprint.get('timezone')} "
            f"screen: {fingerprint.get('screen', {}).get('width')}x"
            f"{fingerprint.get('screen', {}).get('height')}"
        )
        print(f"[4/6] 浏览器出口 IP: {egress.get('primary')}")

        if probe_only:
            _save_report(report, out_dir)
            print(
                f"[probe-only] 探测完成，报告已保存 -> {out_dir}/account.json"
                "（跳过扫码登录）"
            )
            return 0

        print()
        print("=" * 70)
        print("[5/6] 请用手机抖音扫码登录")
        print("      二维码图片: " + str(out_dir / "qrcode_full.png"))
        print("      需要手动操作时（控制台直接回车确认）：")
        print("        点 <按钮文本>      按页面文本点击元素（推荐）")
        print("        选择器 <css选择器> 按 CSS 选择器点击")
        print("        验证码 按4-8位数字回车即可自动输入并提交")
        print("        也可输入 quit 退出，或 pixel x y 按整图像素坐标点击")
        print("=" * 70)

        scanned = await scanner.run_prepared(
            on_qr,
            on_confirming,
            cancelled,
            on_view=on_view,
            next_interaction=next_interaction,
        )

        account = {
            "display_name": scanned.display_name,
            "unique_id": scanned.unique_id,
            "conversation_names": list(scanned.conversation_names),
            "contact_identities": [
                _identity_dict(identity) for identity in scanned.contact_identities
            ],
            "storage_state": scanned.storage_state,
        }
        report["account"] = account
        _save_report(report, out_dir)

        print()
        print(f"[6/6] 登录成功，结果已保存 -> {out_dir / 'account.json'}")
        print(f"      显示名: {scanned.display_name}   抖音号: {scanned.unique_id}")
        print(f"      出口 IP: {egress.get('primary')}   context_mode: {instance.context_mode}")
        return 0
    except ScanCancelled:
        print("\n[取消] 扫码流程被终止")
        _save_report(report, out_dir)
        return 1
    except LoginTimedOut:
        print("\n[超时] 登录等待超时")
        _save_report(report, out_dir)
        return 1
    except VerificationRequired:
        print("\n[验证] 触发安全验证但未自动完成")
        _save_report(report, out_dir)
        return 1
    except QrLoadFailed:
        print("\n[失败] 未能在登录页找到二维码")
        _save_report(report, out_dir)
        return 1
    except Exception as exc:
        print(f"\n[失败] {type(exc).__name__}: {exc}")
        _save_report(report, out_dir)
        return 1
    finally:
        try:
            await scanner.close()
        except Exception:
            pass
        print(f"[done] 报告保存位置: {out_dir / 'account.json'}")


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(
        description="通过远程 cloakbrowser 浏览器完成抖音扫码登录，保存指纹/账号/出口 IP"
    )
    parser.add_argument(
        "base",
        nargs="?",
        default=os.environ.get("REMOTE_BROWSER_BASE") or DEFAULT_BASE,
    )
    parser.add_argument(
        "--seed",
        default=os.environ.get("REMOTE_BROWSER_SEED") or DEFAULT_SEED,
    )
    parser.add_argument("--out-dir", default=None)
    parser.add_argument("--timeout", type=float, default=900.0)
    parser.add_argument("--probe-only", action="store_true")
    args = parser.parse_args(argv)

    base = args.base.rstrip("/")
    if args.out_dir:
        out_dir = Path(args.out_dir).resolve()
    else:
        out_dir = Path(__file__).resolve().parent / "remote_login_output"
    out_dir.mkdir(parents=True, exist_ok=True)

    try:
        return asyncio.run(run(base, args.seed, out_dir, args.timeout, args.probe_only))
    except KeyboardInterrupt:
        print("\n[退出] 用户中断")
        return 130


if __name__ == "__main__":
    sys.exit(main())