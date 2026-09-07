"""Real browser, local synthetic DOM only; never contacts Douyin or sends real messages."""
import asyncio
import sys
from pathlib import Path
from unittest.mock import patch
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from playwright.async_api import async_playwright
from core.handlers.douyin_spark import _select_and_send as send, confirm_message_visible, MESSAGE_COUNT_JS, _message_query
from core.services.contacts import collect_visible


async def _select_and_send(page, name, message, before_send):
    return await send(page, name, message, before_send, target_sec_uid='stable-friend')

HTML = '''<div class="conversationConversationItemwrapper"><a href="https://www.douyin.com/user/stable-friend"><span class="conversationConversationItemtitle">friend</span></a></div>
<section id="chat"><a id="recipient" href="https://www.douyin.com/user/stable-friend">profile</a>
<div id="history"><span>hello</span></div>
<div class="messageEditorimChatEditorContainer" contenteditable="true"></div></section>
<script>document.querySelector('.conversationConversationItemwrapper a').addEventListener('click', e => e.preventDefault())</script>
<script>document.querySelector('[contenteditable]').addEventListener('keydown', event => {
  if(event.key === 'Enter') { event.preventDefault(); const msg = event.target.innerText;
    event.target.innerText = ''; if(window.addMessage) { const el = document.createElement('span'); el.innerText=msg; document.querySelector('#history').appendChild(el); }
  }
});</script>'''

async def main():
    async with async_playwright() as p:
        browser = await p.chromium.launch(channel='msedge', headless=True)
        page = await browser.new_page()
        await page.route('**/*', lambda route: route.fulfill(status=200, content_type='text/html', body=HTML))
        claims = []
        async def before_send(): claims.append('send')
        original_confirm = confirm_message_visible
        async def short_confirm(page, editor, message, baseline):
            return await original_confirm(page, editor, message, baseline, timeout=300)
        with patch('core.handlers.douyin_spark.confirm_message_visible', short_confirm):
            # An old identical message and an emptied editor are not enough.
            result = await _select_and_send(page, 'friend', 'hello', before_send)
            assert result['status'] == 'uncertain', result
            assert len(claims) == 1
            await page.add_init_script('window.addMessage = true')
            result = await _select_and_send(page, 'friend', 'hello', before_send)
            assert result['status'] == 'submitted', result
            assert len(claims) == 2
            # Permission failure happens before Enter, so no message can appear.
            async def denied(): raise RuntimeError('execution revoked')
            try:
                await _select_and_send(page, 'friend', 'hello', denied)
            except RuntimeError:
                pass
            else: raise AssertionError('revoked send was allowed')
            assert await page.evaluate(MESSAGE_COUNT_JS, _message_query('hello')) == 1
            # Ambiguous names must fail before acquiring sending permission.
            duplicate = HTML.replace('<div id="history">', '<div class="conversationConversationItemwrapper"><a href="https://www.douyin.com/user/stable-friend"><span class="conversationConversationItemtitle">friend</span></a></div><div id="history">')
            await page.unroute('**/*')
            await page.route('**/*', lambda route: route.fulfill(status=200, content_type='text/html', body=duplicate))
            try:
                await _select_and_send(page, 'friend', 'hello', before_send)
            except RuntimeError:
                pass
            else: raise AssertionError('ambiguous recipient accepted')
            assert len(claims) == 2
            # Same display name with a different UID is safe to distinguish.
            distinct = duplicate
            marker = '<div class="conversationConversationItemwrapper"><a href="https://www.douyin.com/user/stable-friend"><span'
            position = distinct.rfind(marker)
            distinct = distinct[:position] + distinct[position:].replace('/user/stable-friend', '/user/someone-else', 1)
            await page.unroute('**/*')
            await page.route('**/*', lambda route: route.fulfill(status=200, content_type='text/html', body=distinct))
            assert (await _select_and_send(page, 'renamed-friend', 'hello', before_send))['status'] == 'submitted'
            contacts = await collect_visible(page)
            assert set(contacts) == {'stable-friend', 'someone-else'}
            async def switch_recipient():
                await page.locator('#recipient').evaluate("a => a.href = 'https://www.douyin.com/user/other-person'")
            try:
                await _select_and_send(page, 'friend', 'hello', switch_recipient)
            except RuntimeError:
                pass
            else:
                raise AssertionError('changed chat recipient accepted')
            assert await page.evaluate(MESSAGE_COUNT_JS, _message_query('hello')) == 1
            try:
                await send(page, 'friend', 'hello', before_send)
            except RuntimeError:
                pass
            else:
                raise AssertionError('missing stable UID accepted')
        await browser.close()
    print('Old message rejection, new-page evidence, denied send and ambiguous recipient: PASS')

asyncio.run(main())
