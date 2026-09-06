"""Optional real-browser UI regression with isolated API fixtures (no cloud calls).

Run while Vite is serving localhost:5175: python tests/ui_scheduling_smoke.py
Uses installed Microsoft Edge and writes screenshots to ignored .local-dev/.
"""
import json
import re
from pathlib import Path
from urllib.parse import urlsplit
from playwright.sync_api import sync_playwright

ROOT = Path(__file__).resolve().parents[1]
OUT = ROOT / '.local-dev'
OUT.mkdir(exist_ok=True)


def main():
    with sync_playwright() as p:
        browser = p.chromium.launch(channel='msedge', headless=True)
        context = browser.new_context(viewport={'width': 1360, 'height': 1000})
        errors = []
        tasks = [dict(id='task-1', account_id='account-1', target_name='小林', target_sec_uid='',
                      send_time='08:30', message_template='早上好，新的一天继续加油。', enabled=True,
                      next_run_at=None, schedule_state='error', schedule_error='测试：权限不足'),
                 dict(id='task-2', account_id='account-1', target_name='阿宇', target_sec_uid='',
                      send_time='21:00', message_template='今天也辛苦了，晚安。', enabled=True,
                      next_run_at=None, schedule_state='synced', schedule_error='')]
        deployment = None
        install_page = False
        mutations = []

        def route(request):
            nonlocal deployment
            path = urlsplit(request.request.url).path
            data = {}
            if path == '/api/auth/me':
                data = dict(user=dict(id='test-admin', username='admin', role='admin'), is_admin=True, must_change_password=False, csrf_token='fixture')
            elif path == '/api/tasks':
                data = dict(items=tasks, quota=dict(limit=10, active_usage=2, saved_usage=2, max_saved_tasks=50, grants=[]))
            elif path.endswith('/sync'):
                tasks[0]['schedule_state'] = 'synced'
                data = tasks[0]
            elif path == '/api/accounts':
                data = dict(items=[dict(id='account-1', display_name='我的抖音', validation_state='valid')])
            elif path == '/api/install/status':
                data = dict(mode='cloud', installed=not install_page, needsInstall=install_page, canDeploy=True, missingEnv=[], deployment=deployment)
            elif path == '/api/install/refresh':
                if deployment and deployment['rawStatus'] == 'DELETE_IN_PROGRESS':
                    deployment = {**deployment, 'rawStatus': 'DELETE_COMPLETE', 'status': 'CREATE_FAILED'}
                data = deployment
            elif path == '/api/install/cleanup':
                mutations.append(json.loads(request.request.post_data))
                deployment = {**deployment, 'rawStatus': 'DELETE_IN_PROGRESS', 'status': 'CREATE_IN_PROGRESS'}
                data = deployment
            elif path == '/api/install/reset':
                mutations.append(json.loads(request.request.post_data))
                deployment = None
                data = {'ok': True}
            request.fulfill(status=200, content_type='application/json', body=json.dumps(data))

        context.route(re.compile(r'^http://127\.0\.0\.1:5175/api/'), route)
        page = context.new_page()
        page.on('pageerror', lambda e: errors.append(str(e)))
        page.goto('http://127.0.0.1:5175/tasks')
        page.get_by_text('小林', exact=True).wait_for()
        page.screenshot(path=str(OUT / 'tasks-desktop.png'), full_page=True)
        page.get_by_placeholder('搜索好友或消息').fill('小林')
        assert page.get_by_text('阿宇', exact=True).count() == 0
        page.get_by_role('button', name='同步', exact=True).click()
        page.get_by_text('调度已同步', exact=True).wait_for()
        page.get_by_placeholder('搜索好友或消息').fill('')
        page.set_viewport_size({'width': 390, 'height': 844})
        page.screenshot(path=str(OUT / 'tasks-mobile.png'), full_page=True)
        assert page.evaluate('document.documentElement.scrollWidth <= innerWidth'), 'task page overflows on mobile'
        install_page = True
        deployment = dict(stackId='fixture-stack', status='CREATE_FAILED', rawStatus='CREATE_FAILED', statusReason='测试：资源配额不足', events=[])
        page.set_viewport_size({'width': 1360, 'height': 1000})
        page.goto('http://127.0.0.1:5175/install')
        delete = page.get_by_role('button', name='删除失败的资源栈', exact=True)
        delete.wait_for()
        assert delete.is_disabled()
        page.get_by_placeholder('fixture-stack', exact=True).fill('wrong-stack')
        assert delete.is_disabled()
        page.screenshot(path=str(OUT / 'install-recovery-desktop.png'), full_page=True)
        page.set_viewport_size({'width': 390, 'height': 844})
        page.screenshot(path=str(OUT / 'install-recovery-mobile.png'), full_page=True)
        assert page.evaluate('document.documentElement.scrollWidth <= innerWidth'), 'installer overflows on mobile'
        page.get_by_placeholder('fixture-stack', exact=True).fill('fixture-stack')
        delete.click()
        reset = page.get_by_role('button', name='重新填写部署配置', exact=True)
        reset.wait_for()
        page.get_by_placeholder('fixture-stack', exact=True).fill('fixture-stack')
        reset.click()
        page.get_by_role('button', name='下一步', exact=True).wait_for()
        assert mutations == [{'confirmation': 'fixture-stack'}, {'confirmation': 'fixture-stack'}]
        assert not errors, errors
        browser.close()
    print('Desktop/mobile task search, sync, recovery confirmation and reinstall UI: PASS')


if __name__ == '__main__':
    main()
