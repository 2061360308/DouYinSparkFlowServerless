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
from core.task.execution_contract import message_fingerprint
from core.handlers.recipient import RecipientError, select_recipient, verify_open_recipient

logger = logging.getLogger(__name__)

WEB_CHAT_URL = "https://www.douyin.com/chat"
CONVERSATION_ITEM_SELECTOR = ".conversationConversationItemwrapper"
CONVERSATION_TITLE_SELECTOR = ".conversationConversationItemtitle"
CHAT_EDITOR_SELECTOR = ".messageEditorimChatEditorContainer"
MESSAGE_COUNT_JS = '''({text, baseline, editorSelector, conversationSelector}) => {
  const candidates = [...document.querySelectorAll('body *')].filter(el =>
    !el.closest(editorSelector) && !el.closest(conversationSelector) &&
    el.getClientRects().length && (el.innerText || '').trim() === text.trim());
  const leaves = candidates.filter(el => !candidates.some(child => child !== el && el.contains(child)));
  return baseline == null ? leaves.length : leaves.length > baseline;
}'''


def _message_query(message, baseline=None):
    return {'text': message, 'baseline': baseline, 'editorSelector': CHAT_EDITOR_SELECTOR,
            'conversationSelector': CONVERSATION_ITEM_SELECTOR}


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


async def _select_and_send(page, target_name: str, message: str, before_send, *, target_sec_uid: str = '') -> dict:
    """Stable ID is mandatory; display name is presentation only."""
    if not target_sec_uid:
        raise RecipientError('任务未绑定好友稳定 ID，请同步好友列表并重新选择好友。')
    await page.goto(WEB_CHAT_URL, wait_until="domcontentloaded")
    await page.wait_for_selector(CONVERSATION_ITEM_SELECTOR, timeout=30000)
    await select_recipient(page, target_sec_uid, CONVERSATION_ITEM_SELECTOR)
    editor = page.locator(CHAT_EDITOR_SELECTOR).first
    await editor.wait_for(state="visible", timeout=30000)
    await verify_open_recipient(editor, target_sec_uid, CONVERSATION_ITEM_SELECTOR)
    # Count exact text outside the editor before composing; old messages cannot confirm a new send.
    baseline = await page.evaluate(MESSAGE_COUNT_JS, _message_query(message))
    await editor.fill(message)
    await before_send()
    await verify_open_recipient(editor, target_sec_uid, CONVERSATION_ITEM_SELECTOR)
    try:
        await editor.press('Enter')
        await confirm_message_visible(page, editor, message, baseline)
    except Exception:
        return {'ok': False, 'status': 'uncertain', 'reason': '已进入发送阶段，但未确认新增消息。请检查聊天记录，不会自动重发。'}
    return {'ok': True, 'status': 'submitted', 'reason': '编辑框已清空且页面出现新增消息；未验证服务端送达或对方已读。'}


async def confirm_message_visible(page, editor, message: str, baseline: int, timeout: int = 15000):
    """Page evidence only: editor clears and exact matching text count increases."""
    handle = await editor.element_handle()
    if handle is None:
        raise RuntimeError('编辑框已离开页面')
    await page.wait_for_function('(editor) => !editor.innerText.trim()', arg=handle, timeout=timeout)
    # Text is passed as data, never interpolated into a selector or JavaScript source.
    await page.wait_for_function(MESSAGE_COUNT_JS, arg=_message_query(message, baseline), timeout=timeout)


@handler("douyin_spark")
async def run(task: dict) -> dict:
    client = get_client()
    params = task.get("params") or {}
    spark_task_id = params.get("spark_task_id")
    execution = task.get('_execution')
    if not execution or not execution.get('claimed'):
        raise RuntimeError('缺少执行权，禁止发送')
    if not spark_task_id:
        raise ValueError("params.spark_task_id 缺失")

    spark = await client.get_spark_task(spark_task_id)
    account_id = spark.get("account_id")
    target_name = spark.get("target_name")
    message = spark.get("message_template") or "续火花"
    if not account_id:
        return {"ok": False, 'status': 'failed', "reason": "任务未绑定抖音账号"}

    cookie_info = await client.get_account_cookies(account_id)
    context_kwargs, cookies = _parse_cookies(
        cookie_info["cookies_json"], int(cookie_info.get("cookie_version", 1))
    )

    br = await client.acquire_browser(f"douyin_{account_id}")
    ws_url, headers = br.get("ws_url"), br.get("headers") or {}
    if not ws_url:
        return {"ok": False, 'status': 'failed', "reason": "申请远程浏览器失败"}

    # 延迟导入 playwright：仅执行时需要，导入本模块不强依赖
    from playwright.async_api import async_playwright

    async def before_send():
        await client.begin_send(execution['run_id'], execution['token'], message_fingerprint(spark))
    result = None
    async with async_playwright() as pw:
        browser = await pw.chromium.connect_over_cdp(ws_url, headers=headers)
        try:
            context = await browser.new_context(**context_kwargs)
            if cookies:
                await context.add_cookies(cookies)
            page = await context.new_page()
            try:
                result = await _select_and_send(page, target_name, message, before_send,
                                                target_sec_uid=spark.get('target_sec_uid') or '')
            except RecipientError as error:
                result = {'ok': False, 'status': 'failed', 'reason': str(error)}
        finally:
            try:
                await browser.close()
            except Exception:
                logger.warning('浏览器连接关闭失败 spark_task=%s', spark_task_id)
    return result
