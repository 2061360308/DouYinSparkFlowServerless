"""Conservative recipient binding from public profile links, never display names.

This is a DOM adapter, not a claim about a stable Douyin DOM contract. If the
site stops exposing an unambiguous profile link we stop before sending.
"""
from urllib.parse import urlsplit, unquote


class RecipientError(RuntimeError):
    pass


def profile_uid(href: str) -> str | None:
    try:
        url = urlsplit(href)
        if url.scheme != 'https' or url.hostname != 'www.douyin.com' or url.username or url.password or url.port not in (None, 443):
            return None
        parts = url.path.strip('/').split('/')
        if len(parts) != 2 or parts[0] != 'user':
            return None
        uid = unquote(parts[1])
        if not uid or len(uid) > 256 or any(c.isspace() or c in '/?#' for c in uid):
            return None
        return uid
    except ValueError:
        return None


async def item_uids(item) -> set[str]:
    links = await item.locator('a[href]').evaluate_all('(links) => links.filter(a => a.getClientRects().length).map(a => a.href)')
    return {uid for href in links if (uid := profile_uid(href))}


async def select_recipient(page, target_uid, item_selector):
    if not target_uid:
        raise RecipientError('任务未绑定好友稳定 ID，请重新同步好友列表并选择好友，不按昵称发送。')
    matches = []
    for item in await page.locator(item_selector).all():
        if await item.is_visible() and await item_uids(item) == {target_uid}:
            matches.append(item)
    if len(matches) != 1:
        raise RecipientError('未找到唯一匹配好友 ID 的会话，请刷新好友列表后重试。')
    await matches[0].click()
    return matches[0]


async def verify_open_recipient(editor, target_uid, item_selector):
    # Find the nearest chat container with profile links, excluding sidebar rows
    # and the editable message itself. Conflicting IDs are not resolved by name.
    links = await editor.evaluate('''(editor, itemSelector) => {
      for (let parent = editor.parentElement; parent; parent = parent.parentElement) {
        const links = [...parent.querySelectorAll('a[href]')].filter(a =>
          !a.closest(itemSelector) && !editor.contains(a) && a.getClientRects().length);
        const profiles = links.filter(a => { try {
          const u = new URL(a.href); return u.hostname === 'www.douyin.com' && u.pathname.startsWith('/user/');
        } catch { return false; } });
        if (profiles.length) return profiles.map(a => a.href);
      }
      return [];
    }''', item_selector)
    if {uid for href in links if (uid := profile_uid(href))} != {target_uid}:
        raise RecipientError('当前聊天窗口的好友 ID 无法确认或已切换，已停止发送。')
