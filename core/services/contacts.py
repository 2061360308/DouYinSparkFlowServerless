"""Read-only browser scan; merge positively identified contacts without deleting others."""
import logging
import secrets
from tortoise.transactions import in_transaction
from core.browser import BrowserManager
from core.db.models import DouyinAccount, DouyinContactIdentity
from core.handlers.recipient import item_uids
from core.handlers.douyin_spark import _parse_cookies, WEB_CHAT_URL, CONVERSATION_ITEM_SELECTOR, CONVERSATION_TITLE_SELECTOR
from core.services import ValidationError, NotFound


async def collect_visible(page) -> dict[str, str]:
    await page.goto(WEB_CHAT_URL, wait_until='domcontentloaded', timeout=30000)
    await page.wait_for_selector(CONVERSATION_ITEM_SELECTOR, timeout=15000)
    contacts = {}
    for item in await page.locator(CONVERSATION_ITEM_SELECTOR).all():
        if not await item.is_visible():
            continue
        uids = await item_uids(item)
        if len(uids) != 1:
            continue
        name = (await item.locator(CONVERSATION_TITLE_SELECTOR).inner_text()).strip()
        if name:
            contacts[next(iter(uids))] = name[:256]
    if not contacts:
        raise ValidationError('未能读取带稳定 ID 的会话，请确认账号已登录且页面显示好友资料链接。旧列表已保留。')
    return contacts


async def sync_contacts(account, cipher) -> int:
    from playwright.async_api import async_playwright
    try:
        kwargs, cookies = _parse_cookies(cipher.decrypt(account.encrypted_cookies, account.cookie_nonce).decode(), account.cookie_version)
    except Exception:
        raise ValidationError('账号凭据无法读取，请重新登录账号') from None
    manager = await BrowserManager.get_instance()
    session = 'contacts_' + secrets.token_hex(12)
    browser_info = await manager.acquire(session)
    if not browser_info.get('ok'):
        raise ValidationError('浏览器资源暂不可用，请稍后同步')
    try:
        async with async_playwright() as pw:
            browser = await pw.chromium.connect_over_cdp(browser_info['ws_url'], headers=browser_info.get('headers') or {})
            try:
                context = await browser.new_context(**kwargs)
                if cookies:
                    await context.add_cookies(cookies)
                contacts = await collect_visible(await context.new_page())
            finally:
                await browser.close()
    except ValidationError:
        raise
    except Exception:
        raise ValidationError('好友同步失败，旧列表已保留；请检查登录状态后重试') from None
    finally:
        try:
            await manager.destroy(session)
        except Exception:
            logging.warning('Contact scan browser cleanup failed')
    async with in_transaction():
        if not await DouyinAccount.filter(id=account.id).select_for_update().first():
            raise NotFound('account not found')
        for uid, name in contacts.items():
            await DouyinContactIdentity.update_or_create(account_id=account.id, sec_uid=uid, defaults={'remark_name': name})
    return len(contacts)
