"""验证远程 cloakbrowser 登录态续存：换新 sessionID 触发新云函数实例，
注入上一次登录的 storage_state，打开抖音聊天界面验证登录状态是否仍在。

用法:
    python tests/verify_login_scan.py [ACCOUNT_JSON] [BASE_URL]
        [--seq 1] [--out-dir DIR] [--send-to 王泽] [--message 在吗？]

默认 ACCOUNT_JSON: tests/remote_login_output/account.json（第一个脚本的产物）
--send-to 复用 core/tasks.py + core/web_chat.py 的发消息流程，验证完成后
给目标好友发一条消息（默认不发送，避免频繁换 IP 触发风控）。
"""
from __future__ import annotations

import argparse
import asyncio
import json
import os
import sys
from datetime import datetime
from pathlib import Path
from urllib.parse import urlparse


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

from core.web_chat import (  # noqa: E402
    CHAT_EDITOR_SELECTOR,
    CONVERSATION_ITEM_SELECTOR,
    TargetNotFoundError,
    page_has_web_chat_login_prompt,
    select_web_chat_target,
)
from remote_login_scan import (  # noqa: E402
    FINGERPRINT_JS,
    RemoteBrowserSession,
    build_session_id,
    derive_ws_url,
    encode_cfg_header,
    probe_egress_ips,
    probe_fingerprint,
    start_browser,
)

DEFAULT_ACCOUNT_JSON = Path(__file__).resolve().parent / "remote_login_output" / "account.json"
DEFAULT_BASE = "https://browser-test-nlbmudxesk.cn-hangzhou.fcapp.run"
CHAT_URL = "https://www.douyin.com/chat"


async def _capture_account_info(page) -> dict:
    try:
        return await page.evaluate(
            """async () => {
                    try {
                      const resp = await fetch("/passport/account/info/v2/?aid=6383", {credentials: "include"});
                      const raw = await resp.text();
                      let body = null;
                      try { body = JSON.parse(raw); } catch (e) {}
                      const okData = !!(body && body.data);
                      return {
                        http_status: resp.status,
                        authenticated: !!(body && body.message === "success" && okData && body.data.user_id),
                        body: body,
                      };
                    } catch (e) {
                      return { http_status: 0, authenticated: false, body: null, error: String(e) };
                    }
                }"""
        )
    except Exception:
        return {"http_status": 0, "authenticated": False, "body": None}


def _slim_body(body) -> dict | None:
    if not isinstance(body, dict):
        return None
    data = body.get("data") if isinstance(body, dict) else None
    if not isinstance(data, dict):
        return {"top_level_keys": sorted(body.keys())}
    picked = {
        "user_id": data.get("user_id"),
        "sec_uid": data.get("sec_user_id") or data.get("sec_uid"),
    }
    user = data.get("user_info")
    if isinstance(user, dict):
        picked["name"] = user.get("nickname") or user.get("name") or user.get("screen_name")
        picked["unique_id"] = user.get("unique_id") or user.get("short_id")
    else:
        picked["name"] = data.get("name") or data.get("screen_name")
        picked["unique_id"] = data.get("unique_id") or data.get("short_id")
        picked["data_keys"] = sorted(data.keys())
    return picked


async def _settle_and_capture(page, screenshot_path: Path) -> None:
    for wait_until in ("load", "networkidle"):
        try:
            await page.wait_for_load_state(wait_until, timeout=45_000)
            break
        except Exception:
            continue
    try:
        await page.wait_for_selector(
            CONVERSATION_ITEM_SELECTOR, state="visible", timeout=25_000
        )
    except Exception:
        pass
    await asyncio.sleep(2)
    await page.screenshot(path=str(screenshot_path), full_page=False)


def _aliases_for_target(account: dict, target: str) -> tuple[str, ...]:
    """Collect all names of the target from the saved contact identities."""
    aliases = [target]
    for identity in account.get("contact_identities") or ():
        values = [
            identity.get("remark_name"),
            identity.get("nickname"),
            identity.get("unique_id"),
            identity.get("short_id"),
            identity.get("sec_uid"),
        ]
        if target in {str(value) for value in values if value}:
            aliases = [str(value) for value in values if value]
            break
    return tuple(dict.fromkeys(aliases))


async def send_message_to_target(
    page, target: str, aliases: tuple[str, ...], message: str, out_dir: Path
) -> dict:
    """Select 王泽-style conversation and send a message (tasks.py/web_chat.py 逻辑)."""
    from core.tasks import confirm_message_sent  # 延迟导入，避免平台配置副作用

    picked = {
        "target": target,
        "aliases": list(aliases),
        "message": message,
        "ok": False,
        "selected": None,
        "error": None,
    }
    try:
        await page.wait_for_load_state("load", timeout=60_000)
        if await page_has_web_chat_login_prompt(page):
            raise RuntimeError("页面已回到登录态，无法发送消息")
        selected = await select_web_chat_target(page, target, aliases=aliases)
        picked["selected"] = selected
        print(f"      [已选中好友] {selected}，等待聊天输入框…")
        await page.wait_for_selector(CHAT_EDITOR_SELECTOR, timeout=30_000)
        chat_input = page.locator(CHAT_EDITOR_SELECTOR).first
        lines = message.split("\n")
        for index, line in enumerate(lines):
            await chat_input.type(line)
            if index < len(lines) - 1:
                await chat_input.press("Shift+Enter")
        await asyncio.sleep(1)
        await chat_input.press("Enter")
        await confirm_message_sent(page, chat_input, message)
        picked["ok"] = True
    except Exception as exc:
        picked["error"] = f"{type(exc).__name__}: {exc}"
        try:
            stamp = datetime.now().strftime("%Y%m%d_%H%M%S")
            await page.screenshot(
                path=str(out_dir / f"chat_send_failed_{stamp}.png"), full_page=False
            )
        except Exception:
            pass
    finally:
        try:
            await page.wait_for_load_state("load", timeout=30_000)
        except Exception:
            pass
        try:
            await page.screenshot(
                path=str(out_dir / f"chat_sent_{picked['selected'] or target}.png"),
                full_page=False,
            )
        except Exception:
            pass
    return picked


async def run(
    base: str,
    account_json: Path,
    out_dir: Path,
    seq: int,
    send_to: str | None = None,
    message: str = "在吗？",
) -> int:
    data = json.loads(account_json.read_text(encoding="utf-8"))
    account = data.get("account") or {}
    storage_state = account.get("storage_state")
    if not storage_state:
        raise RuntimeError(f"{account_json} 中没有 account.storage_state（需先跑登录脚本）")

    base_cfg = (data.get("browser_fingerprint", {}).get("requested_config") or {}).copy()
    base_cfg.pop("seq", None)
    if not base_cfg.get("seed"):
        raise RuntimeError("account.json 缺少 fingerprint.requested_config.seed")

    sid = build_session_id({**base_cfg, "seq": seq})
    cfg_b64 = encode_cfg_header(base_cfg)
    print(
        f"[1/6] 换新 sessionID (seq={seq}) 启动新云函数实例: {base}\n"
        f"      配置同上次(seed={base_cfg.get('seed')})，但 seq 不同 -> 新实例 -> 大概率新出口IP"
    )
    body = start_browser(base, sid, cfg_b64)
    ws = body.get("ws") or derive_ws_url(base)
    print(f"[2/6] 新实例就绪 ws={ws}  browser={body.get('browser', '')}")

    instance = RemoteBrowserSession(base, sid, cfg_b64)
    instance.ws = ws
    instance.browser_version = body.get("browser", "")

    report = {
        "generated_at": datetime.now().isoformat(),
        "remote_browser": {
            "base_url": base,
            "ws_url": ws,
            "browser_version": body.get("browser", ""),
            "session_id": sid,
            "seq": seq,
            "context_mode": None,
        },
        "injected_account": {
            "display_name": account.get("display_name"),
            "unique_id": account.get("unique_id"),
            "cookies_count": len(storage_state.get("cookies", [])),
            "origins_count": len(storage_state.get("origins", [])),
        },
        "browser_fingerprint": {
            "requested_config": base_cfg,
            "observed": None,
        },
        "egress_ip": None,
        "verification": None,
        "screenshot": None,
    }

    browser = None
    pw = None
    try:
        from playwright.async_api import async_playwright

        pw = await async_playwright().start()
        real = await pw.chromium.connect_over_cdp(
            ws, headers={"sessionID": sid}, timeout=120_000
        )
        browser = real
        ctx = await browser.new_context(storage_state=storage_state)
        instance.context_mode = "new-context"

        page = await ctx.new_page()
        await page.goto(CHAT_URL, wait_until="domcontentloaded", timeout=120_000)

        screenshot_path = out_dir / "chat_login_state.png"
        await _settle_and_capture(page, screenshot_path)
        report["screenshot"] = str(screenshot_path)

        probe_page = await ctx.new_page()
        try:
            fingerprint = await probe_fingerprint(probe_page)
        finally:
            try:
                await probe_page.close()
            except Exception:
                pass
        report["browser_fingerprint"]["observed"] = fingerprint
        report["egress_ip"] = await probe_egress_ips(ctx)
        report["remote_browser"]["context_mode"] = instance.context_mode

        acct_info = await _capture_account_info(page)
        auth_api = bool(acct_info.get("authenticated"))
        has_list = False
        try:
            has_list = (await page.locator(CONVERSATION_ITEM_SELECTOR).count()) > 0
        except Exception:
            pass
        prompt = False
        try:
            prompt = await page_has_web_chat_login_prompt(page)
        except Exception:
            prompt = (await page.get_by_text("扫码登录", exact=True).count()) > 0
        title = ""
        try:
            title = await page.title()
        except Exception:
            pass

        slim = _slim_body(acct_info.get("body"))
        if isinstance(slim, dict) and slim.get("name"):
            report["injected_account"]["display_name"] = slim["name"]
            if slim.get("unique_id"):
                report["injected_account"]["unique_id"] = slim["unique_id"]
            if slim.get("user_id"):
                report["injected_account"]["user_id"] = slim["user_id"]

        raw_json = None
        if isinstance(acct_info.get("body"), dict):
            raw_json = json.dumps(
                acct_info["body"], ensure_ascii=False, separators=(",", ":")
            )[:16_000]
        result = {
            "authenticated": auth_api or has_list,
            "via_api": auth_api,
            "via_ui": has_list,
            "login_prompt_visible": prompt,
            "page_title": title,
            "page_url": page.url,
            "account_info": {
                "http_status": acct_info.get("http_status"),
                "authenticated_api_flag": acct_info.get("authenticated"),
                "message": (acct_info.get("body") or {}).get("message")
                if isinstance(acct_info.get("body"), dict)
                else None,
                "data": slim,
                "raw_json": raw_json,
            },
        }
        report["verification"] = result

        print(f"[3/6] 出口 IP: {report['egress_ip'].get('primary')}")
        print(f"[4/6] 指纹 canvas: {str((fingerprint or {}).get('canvasHash', ''))[:60]}...")
        print(f"[5/6] 登录态验证:")
        print(f"      authenticated = {result['authenticated']}")
        acct = result.get("account_info") or {}
        data = acct.get("data") or {}
        print(f"      via_api={result['via_api']} (http_status={acct.get('http_status')}, "
              f"msg={acct.get('message')}, user_id={data.get('user_id')})")
        print(f"      via_ui={result['via_ui']}  login_prompt={result['login_prompt_visible']}")
        print(f"      page_url={result['page_url']}")
        print(f"      截图 -> {screenshot_path}")

        if send_to:
            print(f"[6/6] 给好友「{send_to}」发送消息…")
            send_result = await send_message_to_target(
                page, send_to, _aliases_for_target(account, send_to), message, out_dir
            )
            report["message_sent"] = send_result
            status = "OK" if send_result["ok"] else f"失败: {send_result['error']}"
            print(f"      发送状态: {status}")
            print(f"      消息内容: {send_result['message']!r}")
            print(f"      截图 -> {out_dir / ('chat_sent_' + (send_result['selected'] or send_to) + '.png')}")
        else:
            print("[6/6] 未指定 --send-to，跳过发消息（避免频繁换 IP 触发风控）")

        result_path = out_dir / "verify_result.json"
        result_path.write_text(
            json.dumps(report, ensure_ascii=False, indent=2, default=str),
            encoding="utf-8",
        )
        print(f"[done] 报告 -> {result_path}")
        return 0
    except Exception as exc:
        print(f"[失败] {type(exc).__name__}: {exc}")
        result_path = out_dir / "verify_result.json"
        result_path.write_text(
            json.dumps(report, ensure_ascii=False, indent=2, default=str),
            encoding="utf-8",
        )
        return 1
    finally:
        try:
            if browser is not None:
                await browser.close()
        except Exception:
            pass
        if pw is not None:
            await pw.stop()


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(
        description="换新云函数实例验证抖音登录态续存（注入 login storage_state）"
    )
    parser.add_argument("account_json", nargs="?", default=str(DEFAULT_ACCOUNT_JSON))
    parser.add_argument(
        "base",
        nargs="?",
        default=os.environ.get("REMOTE_BROWSER_BASE") or DEFAULT_BASE,
    )
    parser.add_argument("--seq", type=int, default=1)
    parser.add_argument("--out-dir", default=None)
    parser.add_argument(
        "--send-to",
        default=None,
        help="登录态验证同时给该好友发一条消息（如 王泽），默认不发送",
    )
    parser.add_argument(
        "--message",
        default="在吗？",
        help="配合 --send-to 使用的消息内容（多行用 \\n）",
    )
    args = parser.parse_args(argv)

    account_json = Path(args.account_json).resolve()
    if not account_json.is_file():
        print(f"[失败] 找不到账号文件: {account_json}")
        return 2
    base = args.base.rstrip("/")
    if args.out_dir:
        out_dir = Path(args.out_dir).resolve()
    else:
        out_dir = (
            Path(__file__).resolve().parent
            / "remote_login_output"
            / f"verify_{datetime.now():%Y%m%d_%H%M%S}"
        )
    out_dir.mkdir(parents=True, exist_ok=True)

    try:
        return asyncio.run(
            run(base, account_json, out_dir, args.seq, args.send_to, args.message)
        )
    except KeyboardInterrupt:
        print("\n[退出] 用户中断")
        return 130


if __name__ == "__main__":
    sys.exit(main())