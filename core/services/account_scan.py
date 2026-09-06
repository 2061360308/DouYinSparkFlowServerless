"""抖音扫码登录服务（API 短连接 + 前端轮询版）。

设计要点
--------
- 不维护扫码状态表，远程浏览器实例即状态源
- ``sessionid`` 复用 ``BrowserManager`` 的 sessionid，无额外映射
- 每个 API 请求都是短操作：重连浏览器 → 查询/操作 → 断开本地连接
- 登录成功后提取 cookie，创建 ``DouyinAccount``，并销毁浏览器释放资源
"""

from __future__ import annotations

import asyncio
import json
import logging
import uuid
from typing import Any

from playwright.async_api import Browser, Page, async_playwright

from core.browser import BrowserManager
from core.crypto import CookieCipher
from core.services import NotFound, ValidationError
from core.services.accounts import AccountService

logger = logging.getLogger(__name__)

CHAT_LOGIN_URL = "https://www.douyin.com/chat"

CONFIRMING_TEXT = ("扫码成功", "请在手机上确认", "已扫码")
VERIFICATION_TEXT = ("安全验证", "请完成验证", "手机验证", "短信验证")
SMS_CODE_INPUT_SELECTORS = (
    'input[placeholder*="验证码"]',
    'input[placeholder*="短信"]',
    'input[type="tel"]',
    'input[maxlength="6"]',
)


class ScanError(Exception):
    """扫码流程业务异常。"""


class DouyinScanService:
    """单次扫码会话服务（按 sessionid 操作远程浏览器）。"""

    def __init__(self, sessionid: str) -> None:
        self.sessionid = sessionid

    # ------------------------------------------------------------------
    # 公共入口
    # ------------------------------------------------------------------
    @classmethod
    async def start(cls, fingerprint: dict[str, Any] | None = None) -> str:
        """申请浏览器并打开抖音登录页，返回 sessionid。"""
        sessionid = uuid.uuid4().hex
        mgr = await BrowserManager.get_instance()
        res = await mgr.acquire(sessionid, **(fingerprint or {}))
        if not res.get("ok"):
            code = res.get("code", 0)
            msg = res.get("msg", "申请浏览器失败")
            if code == 3001:  # ERR_AT_CAPACITY
                raise ScanError("server_busy")
            raise ScanError(f"browser_acquire_failed: {msg}")

        service = cls(sessionid)
        try:
            async with service._page() as page:
                await page.goto(CHAT_LOGIN_URL, wait_until="domcontentloaded", timeout=30_000)
                await service._open_login_panel(page)
        except Exception as error:  # noqa: BLE001
            await mgr.destroy(sessionid)
            raise ScanError(f"open_login_page_failed: {error}") from error
        return sessionid

    async def get_qr(self) -> tuple[str, str | None]:
        """返回 (status, qr_base64)。status 为 loading_qr / awaiting_scan。"""
        async with self._page() as page:
            qr = await self._find_qr(page)
            if qr is None:
                return "loading_qr", None
            b64 = await self._qr_base64_from_element(qr)
            if b64 is None:
                return "loading_qr", None
            return "awaiting_scan", b64

    async def get_status(
        self, owner_user_id: str, cipher: CookieCipher
    ) -> tuple[str, dict[str, Any] | None]:
        """返回 (status, account_dict)。status 可能为 succeeded / confirming /
        verification_required / awaiting_scan / loading_qr / failed。
        succeeded 时会自动创建 DouyinAccount 并销毁浏览器。
        """
        async with self._page() as page:
            status = await self._detect_status(page)
            if status == "succeeded":
                account = await self._finish_success(page, owner_user_id, cipher)
                return "succeeded", account
            return status, None

    async def refresh_qr(self) -> tuple[str, str | None]:
        """代为点击刷新二维码，返回新二维码。"""
        async with self._page() as page:
            qr = await self._find_qr(page)
            if qr is not None:
                try:
                    await qr.click(timeout=3_000)
                except Exception as error:  # noqa: BLE001
                    logger.warning("点击刷新二维码失败: %s", error)
            # 等待新二维码出现（最多 10 秒）
            deadline = asyncio.get_running_loop().time() + 10
            while asyncio.get_running_loop().time() < deadline:
                qr = await self._find_qr(page)
                if qr is not None:
                    b64 = await self._qr_base64_from_element(qr)
                    if b64 is not None:
                        return "awaiting_scan", b64
                await asyncio.sleep(0.3)
            return "loading_qr", None

    async def verify_code(self, code: str) -> str:
        """填写短信验证码并提交，返回最新状态。"""
        code = (code or "").strip()
        if not code or not code.isdigit() or len(code) < 4:
            raise ValidationError("验证码须为 4-6 位数字")

        async with self._page() as page:
            input_locator = None
            for selector in SMS_CODE_INPUT_SELECTORS:
                loc = page.locator(selector).first
                try:
                    if await loc.is_visible(timeout=2_000):
                        input_locator = loc
                        break
                except Exception:  # noqa: BLE001
                    continue
            if input_locator is None:
                # 兜底：尝试找页面上最后一个可见的 input
                for loc in await page.locator("input").all():
                    try:
                        if await loc.is_visible():
                            input_locator = loc
                            break
                    except Exception:  # noqa: BLE001
                        continue
            if input_locator is None:
                return "verification_required"

            await input_locator.fill(code, timeout=5_000)
            # 尝试触发提交（回车或找提交按钮）
            try:
                await input_locator.press("Enter", timeout=3_000)
            except Exception:  # noqa: BLE001
                pass
            try:
                submit = page.locator(
                    'button:has-text("确认"), button:has-text("登录"), button:has-text("提交"), '
                    'button:has-text("确定")'
                ).first
                if await submit.is_visible(timeout=1_000):
                    await submit.click(timeout=3_000)
            except Exception:  # noqa: BLE001
                pass

            await asyncio.sleep(0.5)
            return await self._detect_status(page)

    async def cancel(self) -> None:
        """释放浏览器。"""
        mgr = await BrowserManager.get_instance()
        await mgr.destroy(self.sessionid)

    # ------------------------------------------------------------------
    # 浏览器连接与页面查找
    # ------------------------------------------------------------------
    async def _connect(self) -> Browser:
        mgr = await BrowserManager.get_instance()
        rec = await mgr.get(self.sessionid)
        if not rec or not rec.get("ok"):
            raise NotFound("browser session not found or expired")
        playwright = await async_playwright().start()
        try:
            browser = await playwright.chromium.connect_over_cdp(
                rec["ws_url"], headers=rec.get("headers") or {}
            )
        except Exception as error:  # noqa: BLE001
            await playwright.stop()
            raise NotFound(f"connect to browser failed: {error}") from error
        # 把 playwright 对象挂到 browser 上，便于关闭
        browser._playwright = playwright  # type: ignore[attr-defined]
        return browser

    async def _find_scan_page(self, browser: Browser) -> Page | None:
        for context in browser.contexts:
            for page in context.pages:
                if "douyin.com" in page.url:
                    return page
        if browser.contexts and browser.contexts[0].pages:
            return browser.contexts[0].pages[-1]
        return None

    # ------------------------------------------------------------------
    # 内部页面操作
    # ------------------------------------------------------------------
    async def _open_login_panel(self, page: Page) -> None:
        for label in ("登录", "扫码登录"):
            try:
                button = page.get_by_text(label, exact=True).first
                if await button.is_visible(timeout=2_000):
                    await button.click(timeout=5_000)
                    return
            except Exception:  # noqa: BLE001
                continue
        # 页面可能已经自动弹出登录框，无需点击

    async def _find_qr(self, page: Page) -> Any | None:
        # 精确选择器：抖音登录二维码容器
        try:
            qr = page.locator("#animate_qrcode_container img").first
            if await qr.is_visible(timeout=2_000):
                return qr
        except Exception:  # noqa: BLE001
            pass
        return None

    async def _qr_base64_from_element(self, qr: Any) -> str | None:
        """从 img 元素的 src 属性提取 base64 图片数据。

        抖音二维码通常为 ``data:image/png;base64,xxxx`` 或 ``data:image/jpeg;base64,xxxx``。
        返回纯 base64 字符串（不含 data URL 头）。
        """
        try:
            src: str = await qr.get_attribute("src") or ""
        except Exception as error:  # noqa: BLE001
            logger.warning("读取 QR src 失败: %s", error)
            return None
        if not src:
            return None
        if src.startswith("data:image/"):
            # data:image/png;base64,xxxx
            parts = src.split(",", 1)
            if len(parts) == 2:
                return parts[1]
        # 兜底：如果是普通 URL，暂不处理
        return None

    async def _detect_status(self, page: Page) -> str:
        url = page.url
        if "/creator-micro/" in url or "/passport/account/info/" in url:
            return "succeeded"

        text = ""
        try:
            text = await page.inner_text("body", timeout=2_000)
        except Exception:  # noqa: BLE001
            pass
        text = text or ""

        if any(t in text for t in VERIFICATION_TEXT):
            return "verification_required"
        if any(t in text for t in CONFIRMING_TEXT):
            return "confirming"

        qr = await self._find_qr(page)
        if qr is not None:
            return "awaiting_scan"
        return "loading_qr"

    async def _finish_success(
        self, page: Page, owner_user_id: str, cipher: CookieCipher
    ) -> dict[str, Any]:
        context = page.context
        try:
            cookies = await context.cookies()
        except Exception as error:  # noqa: BLE001
            raise ScanError(f"extract_cookies_failed: {error}") from error

        if not cookies:
            raise ScanError("no_cookies_extracted")

        cookies_json = json.dumps(cookies, ensure_ascii=False)
        display_name = await self._extract_display_name(page) or "抖音账号"

        account_service = AccountService(cipher)
        try:
            account = await account_service.create(owner_user_id, display_name, cookies_json)
        except ValidationError as error:
            raise ScanError(f"create_account_failed: {error}") from error

        # 登录成功后立即释放浏览器
        mgr = await BrowserManager.get_instance()
        await mgr.destroy(self.sessionid)

        return {
            "id": account.id,
            "display_name": account.display_name,
            "validation_state": account.validation_state,
        }

    async def _extract_display_name(self, page: Page) -> str | None:
        try:
            for selector in (
                '[class*="nickname"]',
                '[class*="user-name"]',
                '[class*="display-name"]',
            ):
                text = await page.locator(selector).first.inner_text(timeout=1_000)
                if text:
                    return text.strip()
        except Exception:  # noqa: BLE001
            pass
        return None

    # ------------------------------------------------------------------
    # 异步上下文：自动连接与断开
    # ------------------------------------------------------------------
    class _PageContext:
        def __init__(self, service: "DouyinScanService") -> None:
            self.service = service
            self.browser: Browser | None = None
            self.page: Page | None = None

        async def __aenter__(self) -> Page:
            self.browser = await self.service._connect()
            page = await self.service._find_scan_page(self.browser)
            if page is None:
                await self.service._disconnect(self.browser)
                raise NotFound("douyin login page not found in browser")
            self.page = page
            return page

        async def __aexit__(self, exc_type, exc, tb) -> None:
            if self.browser is not None:
                await self.service._disconnect(self.browser)

    def _page(self) -> "DouyinScanService._PageContext":
        return self._PageContext(self)

    async def _disconnect(self, browser: Browser) -> None:
        playwright = getattr(browser, "_playwright", None)
        try:
            await browser.close()
        except Exception:  # noqa: BLE001
            pass
        if playwright is not None:
            try:
                await playwright.stop()
            except Exception:  # noqa: BLE001
                pass
