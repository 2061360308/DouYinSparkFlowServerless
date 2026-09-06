import asyncio
import base64
import os
from pathlib import Path
import sys

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
os.environ.update(
    SPARK_COOKIE_KEY_B64=base64.b64encode(b'k' * 32).decode(),
    SPARK_SESSION_KEY_B64=base64.b64encode(b's' * 32).decode(),
    SPARK_SERVICE_TOKEN='service-token-for-isolated-tests-32',
    SPARK_PUBLIC_BASE_URL='https://console.example.test',
    SPARK_SECURE_COOKIES='false', SPARK_EMAIL_ENABLED='false',
)
os.environ.pop('DouyinSparkDocker', None)
os.environ.pop('SPARK_DEV_INSECURE', None)

from fastapi.testclient import TestClient
from core.db.init_db import init_db
from core.cli import _create_admin
from core.services import installation
from server.app import create_app


class FakeROS:
    calls = []
    complete = False
    lose_response = True
    missing_output = False
    failure = False
    deletion = ''
    deletes = 0

    def __init__(self, **kwargs):
        assert kwargs['access_key_secret'] == 'test-secret'

    def create_stack(self, **kwargs):
        self.calls.append(kwargs)
        if self.lose_response:
            type(self).lose_response = False
            raise TimeoutError('response lost after creation')
        return 'remote-stack-1'

    def get_stack_status(self, stack_id):
        assert stack_id == 'remote-stack-1'
        if self.deletion:
            return {'Status': self.deletion}
        if self.failure:
            return {'Status': 'CREATE_FAILED', 'StatusReason': 'denied test-secret test-id'}
        if not self.complete:
            return {'Status': 'CREATE_IN_PROGRESS'}
        if self.missing_output:
            return {'Status': 'CREATE_COMPLETE', 'Outputs': []}
        return {'Status': 'CREATE_COMPLETE', 'Outputs': [
            {'OutputKey': key, 'OutputValue': value} for key, value in {
                'TriggerUrlInternet': 'https://browser.example.test',
                'FunctionName': 'DYSparkCloakBrowser',
                'TaskTriggerUrlInternet': 'https://task.example.test',
                'TaskFunctionName': 'DYSparkTaskRunner',
                'EventBusName': 'DouyinSpark-bus',
            }.items()
        ]}

    def delete_stack(self, stack_id):
        assert stack_id == 'remote-stack-1'
        type(self).deletes += 1
        type(self).deletion = 'DELETE_IN_PROGRESS'
        raise TimeoutError('delete response lost')


installation.RosStackClient = FakeROS
asyncio.run(init_db())
asyncio.run(_create_admin('admin', 'test-password-1234', False))
body = {
    'region': 'cn-hangzhou', 'stackName': 'DouyinSpark',
    'credentials': {'accessKeyId': 'test-id', 'accessKeySecret': 'test-secret'},
    'parameters': {'Cpu': '1', 'MemorySize': '1536', 'DiskSize': '512', 'TaskCpu': '0.5', 'TaskMemorySize': '512'},
}

with TestClient(create_app()) as client:
    assert client.get('/api/install/status').status_code == 401
    auth = client.post('/api/auth/login', json={'username': 'admin', 'password': 'test-password-1234'})
    assert auth.status_code == 200, auth.text
    csrf = {'X-CSRF-Token': auth.json()['csrf_token']}
    assert client.get('/api/install/status').status_code == 409
    changed_password = client.post('/api/auth/change-password', json={
        'current_password': 'test-password-1234', 'new_password': 'new-password-5678',
        'new_password_confirmation': 'new-password-5678',
    }, headers=csrf)
    assert changed_password.status_code == 200, changed_password.text
    from core.db.models.user import User
    async def change_role(role):
        await User.filter(username='admin').update(role=role)
    client.portal.call(change_role, 'user')
    assert client.get('/api/install/status').status_code == 404
    assert client.post('/api/install/deploy', json=body, headers=csrf).status_code == 404
    assert client.post('/api/install/refresh', headers=csrf).status_code == 404
    client.portal.call(change_role, 'admin')
    initial = client.get('/api/install/status').json()
    assert initial['needsInstall'] and initial['canDeploy'], initial
    assert client.post('/api/install/deploy', json=body).status_code == 403
    invalid = dict(body, parameters={'TaskDiskSize': '512'})
    assert client.post('/api/install/deploy', json=invalid, headers=csrf).status_code == 400
    invalid = dict(body, parameters={'Cpu': '0.05', 'MemorySize': '1536'})
    assert client.post('/api/install/deploy', json=invalid, headers=csrf).status_code == 400
    first = client.post('/api/install/deploy', json=body, headers=csrf)
    assert first.status_code == 400, first.text
    pending = client.get('/api/install/status').json()['deployment']
    assert pending['stackId'] == '' and pending['status'] == 'CREATE_IN_PROGRESS'
    first = client.post('/api/install/refresh', headers=csrf)
    assert first.status_code == 200, first.text
    assert first.json()['stackId'] == 'remote-stack-1'
    assert client.post('/api/install/deploy', json=body, headers=csrf).status_code == 200
    assert len(FakeROS.calls) == 2
    assert FakeROS.calls[0] == FakeROS.calls[1], 'Recovery must replay the exact persisted request'
    params = FakeROS.calls[0]['parameters']
    assert params['ApiBaseUrl'] == 'https://console.example.test'
    assert params['ServiceToken'] == os.environ['SPARK_SERVICE_TOKEN']
    assert len(params['BearerToken']) >= 32
    assert FakeROS.calls[0]['client_token']
    status = client.get('/api/install/status')
    assert status.json()['deployment']['stackId'] == 'remote-stack-1'
    assert 'test-secret' not in status.text
    assert 'service-token-for' not in status.text
    assert client.post('/api/install/refresh', headers=csrf).json()['status'] == 'CREATE_IN_PROGRESS'
    FakeROS.failure = True
    failed = client.post('/api/install/refresh', headers=csrf)
    assert failed.json()['status'] == 'CREATE_FAILED'
    assert '[redacted]' in failed.text and 'test-secret' not in failed.text and 'test-id' not in failed.text
    assert not client.get('/api/install/status').json()['installed']
    confirmation = {'confirmation': 'remote-stack-1'}
    # A stale failure in our DB must not authorize deleting a recovered cloud stack.
    FakeROS.failure, FakeROS.complete = False, True
    assert client.post('/api/install/cleanup', json=confirmation, headers=csrf).status_code == 409
    assert FakeROS.deletes == 0
    assert client.get('/api/install/status').json()['deployment']['rawStatus'] == 'CREATE_IN_PROGRESS'
    FakeROS.failure, FakeROS.complete = True, False
    assert client.post('/api/install/refresh', headers=csrf).json()['rawStatus'] == 'CREATE_FAILED'
    assert client.post('/api/install/cleanup', json=confirmation).status_code == 403
    assert client.post('/api/install/reset', json=confirmation, headers=csrf).status_code == 409
    assert client.post('/api/install/cleanup', json={'confirmation': 'wrong'}, headers=csrf).status_code == 400
    repaired = client.post('/api/install/credentials', json={**confirmation, 'credentials': body['credentials']}, headers=csrf)
    assert repaired.status_code == 200, repaired.text
    assert client.post('/api/install/cleanup', json=confirmation, headers=csrf).status_code == 400
    assert client.get('/api/install/status').json()['deployment']['rawStatus'] == 'DELETE_REQUESTED'
    assert client.post('/api/install/refresh', headers=csrf).json()['rawStatus'] == 'DELETE_IN_PROGRESS'
    assert FakeROS.deletes == 1, 'Lost delete response must query before deleting again'
    assert client.post('/api/install/reset', json=confirmation, headers=csrf).status_code == 409
    FakeROS.deletion = 'DELETE_COMPLETE'
    assert client.post('/api/install/refresh', headers=csrf).json()['rawStatus'] == 'DELETE_COMPLETE'
    assert client.post('/api/install/reset', json=confirmation, headers=csrf).status_code == 200
    FakeROS.deletion = ''
    FakeROS.failure = False
    assert client.post('/api/install/deploy', json=body, headers=csrf).status_code == 200
    assert FakeROS.calls[-1]['client_token'] != FakeROS.calls[0]['client_token']
    changed = dict(body, parameters={'Cpu': '2', 'MemorySize': '2048'})
    assert client.post('/api/install/deploy', json=changed, headers=csrf).status_code == 409
    from core.browser.manager import BrowserManager
    before = client.portal.call(BrowserManager.get_instance).backend
    assert before.function_url == ''
    FakeROS.complete = True
    FakeROS.missing_output = True
    assert client.post('/api/install/refresh', headers=csrf).status_code == 400
    assert client.get('/api/install/status').json()['installed'] is False
    FakeROS.missing_output = False
    result = client.post('/api/install/refresh', headers=csrf)
    assert result.status_code == 200, result.text
    assert result.json()['status'] == 'CREATE_COMPLETE'
    assert client.get('/api/install/status').json()['installed'] is True
    assert client.post('/api/install/cleanup', json=confirmation, headers=csrf).status_code == 409
    config = client.get('/api/admin/system-config').json()['values']
    assert config['fc_function_url'] == 'https://browser.example.test'
    assert config['eventbridge_bus_name'] == 'DouyinSpark-bus'
    assert config['platform_access_key_secret'] == ''
    assert 'test-secret' not in str(config)
    after = client.portal.call(BrowserManager.get_instance).backend
    assert after is not before
    assert after.function_url == 'https://browser.example.test'
    assert after.ak == 'test-id' and after.sk == 'test-secret'
    assert client.portal.call(BrowserManager.get_instance).backend is after
    from core.db.models.installation import Installation
    async def verify_encryption():
        row = await Installation.get(id=1)
        assert b'test-secret' not in bytes(row.ciphertext)
        assert b'service-token-for' not in bytes(row.ciphertext)
    client.portal.call(verify_encryption)
    # Restoring a completed deployment also repairs accidentally cleared outputs.
    client.portal.call(installation.SystemConfigDB.set_value, 'fc_function_url', '')
    assert client.get('/api/install/status').json()['installed'] is False
    assert client.post('/api/install/refresh', headers=csrf).json()['status'] == 'CREATE_COMPLETE'
    assert client.get('/api/install/status').json()['installed'] is True

# Cold-start restoration uses the persisted record, not browser storage.
with TestClient(create_app()) as client:
    auth = client.post('/api/auth/login', json={'username': 'admin', 'password': 'new-password-5678'})
    state = client.get('/api/install/status').json()
    assert state['installed'] and state['deployment']['stackId'] == 'remote-stack-1'
    from task_scheduling_scenario import check_scheduling
    check_scheduling(client, {'X-CSRF-Token': auth.json()['csrf_token']})

print('Installation auth, validation, deduplication, restore, encryption and completion: PASS')
