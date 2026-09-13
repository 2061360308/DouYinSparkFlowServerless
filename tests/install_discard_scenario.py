"""丢弃「从未创建资源栈的失败请求」：/api/install/discard 的真实场景回归。

覆盖的死锁：创建请求被 ROS 确定性拒绝（如模板校验失败）时记录停留在无栈 ID 状态，
refresh 原样重放旧模板永远失败，而恢复区清理要求 stack_id、重置要求 DELETE_COMPLETE，
管理员只能手动删库。discard 在确认云端未创建后删除记录，允许重新填写部署。

两种守卫：
- 重放依旧被拒绝（模板校验失败 / 凭证非法等）→ 允许丢弃
- 重放取回 stack_id（创建响应丢失、其实已创建成功）→ 拒绝丢弃并回写为正常恢复状态
"""
import asyncio
import base64
import os
from pathlib import Path
import sys

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
_TMP_DB = str(Path(__file__).resolve().parent / 'install_discard.sqlite3')  # 磁盘文件：内存库在 close 后即消失
os.environ.update(
    SPARK_COOKIE_KEY_B64=base64.b64encode(b'k' * 32).decode(),
    SPARK_SESSION_KEY_B64=base64.b64encode(b's' * 32).decode(),
    SPARK_SERVICE_TOKEN='service-token-for-isolated-tests-32',
    SPARK_PUBLIC_BASE_URL='https://console.example.test',
    SPARK_SECURE_COOKIES='false', SPARK_EMAIL_ENABLED='false',
    DATABASE_URL=f'sqlite:///{_TMP_DB}',
)
os.environ.pop('DouyinSparkDocker', None)
os.environ.pop('SPARK_DEV_INSECURE', None)
from pathlib import Path as _Path
try:
    _Path(_TMP_DB).unlink()
except FileNotFoundError:
    pass

from fastapi.testclient import TestClient
from core.db.init_db import init_db
from core.cli import _create_admin
from core.services import installation
from server.app import create_app


class _Rejected(RuntimeError):
    code = 'StackValidationFailed'
    request_id = 'req-rejected'


class FakeROS:
    mode = 'reject'  # reject: 确定性拒绝 | lost: 创建成功但响应丢失
    calls = 0

    def __init__(self, **kwargs):
        assert kwargs['access_key_secret'] == 'test-secret'

    def create_stack(self, **kwargs):
        type(self).calls += 1
        if self.mode == 'reject':
            raise _Rejected('Unknown resource Type : ALIYUN::EventBridge::EventBus')
        if self.mode == 'lost' and type(self).calls == 1:
            raise TimeoutError('response lost after creation')
        return 'remote-stack-1'

    def get_stack_status(self, stack_id):
        assert stack_id == 'remote-stack-1'
        return {'Status': 'CREATE_IN_PROGRESS'}


installation.RosStackClient = FakeROS
asyncio.run(init_db())
asyncio.run(_create_admin('admin', 'test-password-1234', False))
body = {
    'region': 'cn-hangzhou', 'stackName': 'DouyinSpark',
    'credentials': {'accessKeyId': 'test-id', 'accessKeySecret': 'test-secret'},
    'parameters': {'Cpu': '1', 'MemorySize': '1536', 'DiskSize': '512', 'TaskCpu': '0.5', 'TaskMemorySize': '512'},
}

with TestClient(create_app()) as client:
    auth = client.post('/api/auth/login', json={'username': 'admin', 'password': 'test-password-1234'})
    csrf = {'X-CSRF-Token': auth.json()['csrf_token']}
    assert client.post('/api/auth/change-password', json={
        'current_password': 'test-password-1234', 'new_password': 'new-password-5678',
        'new_password_confirmation': 'new-password-5678',
    }, headers=csrf).status_code == 200

    # ── 死锁：确定性拒绝、无栈 ID、恢复区无法清理/重置 ──
    FakeROS.mode = 'reject'
    first = client.post('/api/install/deploy', json=body, headers=csrf)
    assert first.status_code == 400, first.text
    pending = client.get('/api/install/status').json()['deployment']
    assert pending['stackId'] == '' and pending['status'] == 'CREATE_IN_PROGRESS' and pending['rawStatus'] == 'SUBMITTING'
    assert client.post('/api/install/refresh', headers=csrf).status_code == 400  # 原样重放继续失败
    # 无栈 ID：清理入口要求 stack_id，重置要求 DELETE_COMPLETE，两者都不可用
    assert client.post('/api/install/cleanup', json={'confirmation': 'DouyinSpark'}, headers=csrf).status_code == 409
    assert client.post('/api/install/reset', json={'confirmation': 'DouyinSpark'}, headers=csrf).status_code == 409

    # ── discard：确认词错误拒绝 ──
    assert client.post('/api/install/discard', json={'confirmation': 'wrong'}, headers=csrf).status_code == 400

    # ── discard：重放仍被拒绝 → 云端未创建资源，允许丢弃 ──
    discarded = client.post('/api/install/discard', json={'confirmation': 'DouyinSpark'}, headers=csrf)
    assert discarded.status_code == 200, discarded.text
    assert discarded.json() == {'ok': True}
    status = client.get('/api/install/status').json()
    assert status['needsInstall'] and status['deployment'] is None
    # ── 守卫：创建响应丢失（云端其实已创建）→ discard 取回 stack_id 并拒绝丢弃 ──
    FakeROS.mode = 'lost'
    FakeROS.calls = 0
    assert client.post('/api/install/deploy', json=body, headers=csrf).status_code == 400
    blocked = client.post('/api/install/discard', json={'confirmation': 'DouyinSpark'}, headers=csrf)
    assert blocked.status_code == 409, blocked.text  # 拒绝丢弃
    recovered = client.get('/api/install/status').json()['deployment']
    assert recovered['stackId'] == 'remote-stack-1'  # 回写为正常恢复状态
    assert recovered['rawStatus'] == 'CREATE_IN_PROGRESS'
    assert FakeROS.calls == 2  # lost 段内：一次 deploy + 一次 discard 中的幂等重放
    refresh = client.post('/api/install/refresh', headers=csrf)
    assert refresh.status_code == 200 and refresh.json()['stackId'] == 'remote-stack-1'

print('Install discard (unconfirmed request escape hatch + lost-response guard): PASS')