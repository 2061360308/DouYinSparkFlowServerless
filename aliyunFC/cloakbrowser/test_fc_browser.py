"""部署冒烟测试: 连接 FC 上按需启动的 cloakbrowser, 打开抖音验证链路是否打通。

只验证"部署成功"这一件事(**不涉及阿里云 AK/SK**):
  1) GET /start 懒启动浏览器;
  2) Playwright connect_over_cdp 直连, 打开抖音, 截图。

用法:
    python test_fc_browser.py <FC_BASE_URL>
    # 或设环境变量 FC_PUBLIC_BASE=<FC_BASE_URL>
    # FC_BASE_URL 形如 https://<你的函数域名>  (代码不内置任何公网地址)

依赖: pip install playwright && playwright install chromium
"""
import asyncio
import base64
import hashlib
import json
import os
import sys
from urllib.parse import urlsplit
from urllib.request import Request, urlopen

TARGET = "https://www.douyin.com"
CFG = {"seed": "deploy-check", "timezone": "Asia/Shanghai", "locale": "zh-CN"}


def build_headers() -> tuple[str, str]:
    """两个协议头: sessionID=sha256(cfg+seq), X-Browser-Cfg=base64url(cfg)。"""
    sid = hashlib.sha256(
        json.dumps({**CFG, "seq": 0}, sort_keys=True).encode()).hexdigest()
    cfg_b64 = base64.urlsafe_b64encode(
        json.dumps(CFG, sort_keys=True).encode()).decode()
    return sid, cfg_b64


def ws_url(base: str) -> str:
    u = urlsplit(base)
    return f"{'wss' if u.scheme == 'https' else 'ws'}://{u.netloc or u.path}/"


async def main(base: str) -> None:
    sid, cfg_b64 = build_headers()

    # 1) 懒启动
    req = Request(f"{base}/start", method="GET",
                  headers={"sessionID": sid, "X-Browser-Cfg": cfg_b64})
    with urlopen(req, timeout=180) as resp:
        print("start:", json.load(resp).get("status"))

    # 2) 直连并打开抖音
    from playwright.async_api import async_playwright
    async with async_playwright() as p:
        browser = await p.chromium.connect_over_cdp(
            ws_url(base), headers={"sessionID": sid}, timeout=60_000)
        ctx = browser.contexts[0] if browser.contexts else await browser.new_context()
        page = ctx.pages[0] if ctx.pages else await ctx.new_page()
        await page.goto(TARGET, wait_until="domcontentloaded", timeout=45_000)
        await page.wait_for_timeout(2000)
        title = await page.title()
        await page.screenshot(path="deploy_check.png")
        await browser.close()

    assert title, "页面标题为空, 可能未正常加载"
    print(f"[OK] 部署验证通过: title={title!r}, 截图已存 deploy_check.png")


if __name__ == "__main__":
    _base = (sys.argv[1] if len(sys.argv) > 1
             else os.environ.get("FC_PUBLIC_BASE", "")).rstrip("/")
    if not _base:
        sys.exit("用法: python test_fc_browser.py <FC_BASE_URL>  (或设 FC_PUBLIC_BASE)")
    try:
        asyncio.run(main(_base))
    except Exception as exc:  # noqa: BLE001
        sys.exit(f"[FAIL] {type(exc).__name__}: {exc}")
