#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""demo: 纯 URL(不用阿里云 AK) 连接 FC 上的 cloakbrowser + 人类操作模拟。

本示例演示 docs/usage.md 的完整客户端流程, 全程只需公网 URL, **无需 AK/SK**,
也**无需在本地下载 Chromium 二进制**(直连远端 CDP, 不在本地 launch):

  1) 用浏览器配置 cfg 构造两个头:
       sessionID     = sha256(canonical JSON(cfg + seq))   -> FC 亲和会话 ID
       X-Browser-Cfg = base64url(JSON cfg)                 -> 浏览器配置(仅 /start)
  2) GET /start 懒启动, 拿到稳定 wss 根地址;
  3) Playwright connect_over_cdp(ws, headers={"sessionID": sid}) 直连;
  4) cloakbrowser.human.patch_browser_async 一行开启人类模拟(贝塞尔鼠标/逐字符打字);
  5) 人类化 goto / fill / 回车搜索 / 截图。

依赖(客户端):
    pip install playwright cloakbrowser
    playwright install chromium        # 仅为拿到 playwright 的驱动, 不会用其浏览器

用法:
    python demo/connect_demo.py <FC_BASE_URL> ['<cfg json>']
    # FC_BASE_URL 形如 https://<xxx>.cn-<region>.fcapp.run
    # 也可用环境变量 FC_PUBLIC_BASE / DEMO_CFG_JSON 提供

可选环境变量:
    DEMO_TARGET_URL     默认 https://www.bing.com
    DEMO_SEARCH_QUERY   默认 cloakbrowser
    DEMO_HUMAN_PRESET   default | careful (默认 default)
    DEMO_SEQ            会话序号; 想要"全新身份实例"就 +1 (默认 0)
"""
from __future__ import annotations

import asyncio
import base64
import hashlib
import json
import os
import sys
import urllib.error
import urllib.request
from datetime import datetime
from urllib.parse import urlsplit

# ---------------------------------------------------------------------------
# 两个协议头的构造(纯标准库; 与服务端一致)
# ---------------------------------------------------------------------------
SESSION_HEADER = "sessionID"
CFG_HEADER = "X-Browser-Cfg"


def build_session_id(cfg_with_seq: dict) -> str:
    """会话身份 = sha256(canonical JSON(cfg + seq)) 的 64 位 hex。"""
    raw = json.dumps(cfg_with_seq, ensure_ascii=False, sort_keys=True).encode("utf-8")
    return hashlib.sha256(raw).hexdigest()


def encode_cfg_header(base_cfg: dict) -> str:
    """X-Browser-Cfg = base64url(JSON 浏览器配置)。"""
    raw = json.dumps(base_cfg, ensure_ascii=False, sort_keys=True).encode("utf-8")
    return base64.urlsafe_b64encode(raw).decode("ascii")


def derive_ws_url(public_base: str) -> str:
    """从 http(s) 公网地址推导 wss/ws 根地址(GET /start 未回 ws 时的兜底)。"""
    parts = urlsplit(public_base)
    scheme = "wss" if parts.scheme == "https" else "ws"
    netloc = parts.netloc or parts.path  # 兼容裸 host 写法
    return f"{scheme}://{netloc}/"


def http_start(base: str, sid: str, cfg_b64: str, timeout: float = 180.0) -> dict:
    """第 1 步: GET /start 懒启动(只带两个头)。冷启动可能数十秒, 超时给大点。"""
    req = urllib.request.Request(
        f"{base}/start",
        headers={SESSION_HEADER: sid, CFG_HEADER: cfg_b64},
        method="GET",
    )
    try:
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            return json.load(resp)
    except urllib.error.HTTPError as exc:
        try:
            detail = json.load(exc)
        except Exception:  # noqa: BLE001
            detail = {"raw": exc.read().decode("utf-8", "replace")}
        raise SystemExit(f"[FAIL] GET /start HTTP {exc.code}: {detail}") from exc
    except urllib.error.URLError as exc:
        raise SystemExit(f"[FAIL] GET /start 网络错误(云函数可达吗?): {exc}") from exc


# ---------------------------------------------------------------------------
# 主流程
# ---------------------------------------------------------------------------
async def run(base: str, cfg: dict, seq: int, target_url: str,
              query: str, preset: str) -> None:
    # 剔除 None 与 seq: seq 只参与 sessionID 哈希, 不下发到浏览器配置
    base_cfg = {k: v for k, v in cfg.items() if v is not None and k != "seq"}
    sid = build_session_id({**base_cfg, "seq": seq})
    cfg_b64 = encode_cfg_header(base_cfg)
    print(f"[1/5] sessionID={sid[:12]}… seq={seq} cfg_keys={sorted(base_cfg)}")

    print("[2/5] GET /start (懒启动, 冷启动可能较慢) ...")
    body = http_start(base, sid, cfg_b64)
    ws = body.get("ws") or derive_ws_url(base)
    print(f"      ready: browser={body.get('browser', '')} ws={ws}")

    # 延迟导入: 未装依赖时也能 --help / py_compile
    try:
        from playwright.async_api import async_playwright
    except ImportError:
        raise SystemExit("[FAIL] 需要 playwright: pip install playwright && playwright install chromium")
    try:
        from cloakbrowser.human import patch_browser_async, resolve_config
    except ImportError:
        raise SystemExit("[FAIL] 需要 cloakbrowser(人类模拟): pip install cloakbrowser")

    async with async_playwright() as p:
        print("[3/5] connect_over_cdp(ws, sessionID) ...")
        browser = await p.chromium.connect_over_cdp(
            ws, headers={SESSION_HEADER: sid}, timeout=60_000)
        print(f"      connected: version={browser.version}")

        # 一行开启人类模拟: 现有 context/page 与后续 new_page 都会被自动 patch。
        # 注意: patch_browser_async 是同步的"打补丁"函数(非协程), 不要 await。
        patch_browser_async(browser, resolve_config(preset))
        print(f"[4/5] humanize on (preset={preset})")

        ctx = browser.contexts[0] if browser.contexts else await browser.new_context()
        page = ctx.pages[0] if ctx.pages else await ctx.new_page()

        ua = await page.evaluate("navigator.userAgent")
        print(f"      UA: {ua}")

        print(f"[5/5] goto {target_url}")
        await page.goto(target_url, wait_until="domcontentloaded", timeout=45_000)
        await page.wait_for_timeout(1500)

        # 人类化交互: selector 存在才做, 规避不同站点 DOM 差异。务必用基于
        # selector 的 API(page.fill/click), 它们才会走人类化管线。
        try:
            search_box = "textarea[name=q], input[name=q], input[type=search]"
            if await page.locator(search_box).count() > 0:
                await page.fill(search_box, query)      # 逐字符 + 思考停顿
                await page.wait_for_timeout(500)
                await page.keyboard.press("Enter")       # 人类化键盘
                await page.wait_for_load_state("domcontentloaded")
                await page.wait_for_timeout(1500)
                print(f"      人类化搜索完成: {query!r}")
            else:
                await page.mouse.wheel(0, 1200)          # 无搜索框则简单滚动
                await page.wait_for_timeout(800)
                print("      未发现搜索框, 已滚动页面")
        except Exception as exc:  # noqa: BLE001 - 交互失败不影响截图演示
            print(f"      (交互步骤跳过: {type(exc).__name__}: {exc})")

        title = await page.title()
        ts = datetime.now().strftime("%Y%m%d_%H%M%S")
        shot = os.path.join(os.path.dirname(os.path.abspath(__file__)), f"demo_{ts}.png")
        await page.screenshot(path=shot, full_page=False)
        print(f"      title={title!r}")
        print(f"      screenshot -> {shot}")

        # connect_over_cdp 下 close() 仅断开客户端, 服务端浏览器保留复用。
        # 想要全新身份: seq +1 重跑; 想立即停实例: 服务端 FC DeleteSession(需 AK)。
        await browser.close()
    print("[done] 连接演示完成(服务端实例由 FC 空闲回收兜底, 或用 DEMO_SEQ 自增换新)")


def _parse_cfg(raw: str | None) -> dict:
    if not raw:
        return {"seed": "demo-1", "timezone": "Asia/Shanghai", "locale": "zh-CN"}
    try:
        cfg = json.loads(raw)
    except json.JSONDecodeError as exc:
        raise SystemExit(f"[FAIL] cfg 不是合法 JSON: {exc}")
    if not isinstance(cfg, dict):
        raise SystemExit("[FAIL] cfg 必须是 JSON 对象(dict)")
    return cfg


def main(argv: list[str]) -> int:
    if argv[1:2] == ["-h"] or argv[1:2] == ["--help"]:
        print(__doc__)
        return 0

    base = (argv[1] if len(argv) > 1 else os.environ.get("FC_PUBLIC_BASE") or "").rstrip("/")
    if not base:
        print(__doc__)
        raise SystemExit("[FAIL] 缺少 FC_BASE_URL: 传命令行参数或设置环境变量 FC_PUBLIC_BASE")

    cfg = _parse_cfg(argv[2] if len(argv) > 2 else os.environ.get("DEMO_CFG_JSON"))
    seq = int(os.environ.get("DEMO_SEQ", "0") or 0)
    target_url = os.environ.get("DEMO_TARGET_URL", "https://www.bing.com")
    query = os.environ.get("DEMO_SEARCH_QUERY", "cloakbrowser")
    preset = os.environ.get("DEMO_HUMAN_PRESET", "default")
    if preset not in ("default", "careful"):
        raise SystemExit("[FAIL] DEMO_HUMAN_PRESET 只能是 default 或 careful")

    # 概要(不打印 proxy 明文)
    shown = {k: ("<略>" if k == "proxy" else v) for k, v in cfg.items()}
    print(f"[cfg] base={base} cfg={shown} target={target_url} preset={preset}")

    asyncio.run(run(base, cfg, seq, target_url, query, preset))
    return 0


if __name__ == "__main__":
    try:
        sys.exit(main(sys.argv))
    except KeyboardInterrupt:
        sys.exit(130)
