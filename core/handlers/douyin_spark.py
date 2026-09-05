"""续火 handler：定时触发时执行一次「给某好友发消息」。

注册到 task.registry 的 ``douyin_spark`` 事件类别。执行侧不直连数据库，统一经
FastAPI 内部接口取续火任务详情与解密 cookie、申请远程浏览器、回写执行记录；
浏览器动作用 Playwright ``connect_over_cdp`` 连远程 cloakbrowser。

task(ScheduledTask) 的 ``params`` 约定：``{"spark_task_id": "<SparkTask.id>"}``。
DouYin 选择器移植自 tmpcode/DouYinSparkFlow/core/web_chat.py，可按页面变化调整。
"""

from __future__ import annotations

import json
import logging

from core.api_client import get_client
from core.task.registry import handler

logger = logging.getLogger(__name__)

WEB_CHAT_URL = "https://www.douyin.com/chat"
CONVERSATION_ITEM_SELECTOR = ".conversationConversationItemwrapper"
CONVERSATION_TITLE_SELECTOR = ".conversationConversationItemtitle"
CHAT_EDITOR_SELECTOR = ".messageEditorimChatEditorContainer"


def _parse_cookies(cookies_json: str, version: int):
    """返回 (context_kwargs, cookies_to_add)：
    - v2: storage_state 直接传 new_context(storage_state=...)
    - v1: cookie 列表用 add_cookies
    """
    data = json.loads(cookies_json)
    if version >= 2 and isinstance(data, dict):
        storage_state = data.get("storage_state", data)
        return {"storage_state": storage_state}, None
    if isinstance(data, list):
        return {}, data
    raise ValueError("无法识别的 cookie 格式")


async def _select_and_send(page, target_name: str, message: str) -> None:
    """打开会话列表→按标题匹配好友→输入消息→回车发送（移植自 web_chat）。"""
    await page.goto(WEB_CHAT_URL, wait_until="domcontentloaded")
    await page.wait_for_selector(CONVERSATION_ITEM_SELECTOR, timeout=30000)
    matched = None
    for item in await page.locator(CONVERSATION_ITEM_SELECTOR).all():
        try:
            title = (await item.locator(CONVERSATION_TITLE_SELECTOR).inner_text()).strip()
        except Exception:  # noqa: BLE001
            continue
        if title == target_name:
            matched = item
            break
    if matched is None:
        raise RuntimeError(f"未在会话列表找到好友：{target_name}")
    await matched.click()
    editor = page.locator(CHAT_EDITOR_SELECTOR).first
    await editor.wait_for(state="visible", timeout=30000)
    await editor.click()
    await page.keyboard.type(message)
    await page.keyboard.press("Enter")


@handler("douyin_spark")
async def run(task: dict) -> dict:
    client = get_client()
    params = task.get("params") or {}
    spark_task_id = params.get("spark_task_id")
    if not spark_task_id:
        raise ValueError("params.spark_task_id 缺失")

    spark = await client.get_spark_task(spark_task_id)
    account_id = spark.get("account_id")
    target_name = spark.get("target_name")
    message = spark.get("message_template") or "续火花"
    if not account_id:
        await client.write_run(spark_task_id, "failed", stage="no_account",
                               error_code="account_missing", error_summary="任务未绑定抖音账号")
        return {"ok": False, "reason": "account_missing"}

    cookie_info = await client.get_account_cookies(account_id)
    context_kwargs, cookies = _parse_cookies(
        cookie_info["cookies_json"], int(cookie_info.get("cookie_version", 1))
    )

    br = await client.acquire_browser(f"douyin_{account_id}")
    ws_url, headers = br.get("ws_url"), br.get("headers") or {}
    if not ws_url:
        await client.write_run(spark_task_id, "failed", stage="browser",
                               error_code="browser_unavailable", error_summary="申请远程浏览器失败")
        return {"ok": False, "reason": "browser_unavailable"}

    # 延迟导入 playwright：仅执行时需要，导入本模块不强依赖
    from playwright.async_api import async_playwright

    await client.write_run(spark_task_id, "running", stage="sending")
    async with async_playwright() as pw:
        browser = await pw.chromium.connect_over_cdp(ws_url, headers=headers)
        try:
            context = await browser.new_context(**context_kwargs)
            if cookies:
                await context.add_cookies(cookies)
            page = await context.new_page()
            await _select_and_send(page, target_name, message)
        finally:
            await browser.close()

    await client.write_run(spark_task_id, "success", stage="submitted")
    logger.info("续火完成 spark_task=%s target=%s", spark_task_id, target_name)
    return {"ok": True, "target": target_name}
