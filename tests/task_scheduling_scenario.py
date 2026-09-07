"""Run from the isolated installation fixture, using real API/DB and fake EB transport."""
import json
import os
from types import SimpleNamespace

from core.db.models import DouyinAccount, ScheduledTask, User
from core.task import dispatcher


class FakeEB:
    sources = {}
    fail = False
    calls = []

    def response(self, code='Success'):
        return SimpleNamespace(body=SimpleNamespace(success=code == 'Success', code=code))

    def update_event_source(self, request):
        self.calls.append(('update', request.event_source_name))
        if self.fail:
            return self.response('AccessDenied')
        if request.event_source_name not in self.sources:
            return self.response('EventSourceNotExist')
        self.sources[request.event_source_name] = request
        return self.response()

    def create_event_source(self, request):
        self.calls.append(('create', request.event_source_name))
        self.sources[request.event_source_name] = request
        return self.response()

    def delete_event_source(self, request):
        self.calls.append(('delete', request.event_source_name))
        if self.fail:
            return self.response('AccessDenied')
        self.sources.pop(request.event_source_name, None)
        return self.response()


def check_scheduling(client, csrf):
    transport = FakeEB()
    def eb_client(config):
        assert config['platform_access_key_secret'] == 'test-secret'
        assert config['eventbridge_bus_name'] == 'DouyinSpark-bus'
        return transport
    dispatcher._eb_client = eb_client
    async def account():
        user = await User.get(username='admin')
        return await DouyinAccount.create(owner_user_id=user.id, display_name='test account', encrypted_cookies=b'x', cookie_nonce=b'x')
    account_id = client.portal.call(account).id
    from core.db.models import DouyinContactIdentity
    async def contact():
        await DouyinContactIdentity.create(account_id=account_id, sec_uid='fixture-recipient', nickname='friend')
    client.portal.call(contact)
    body = dict(account_id=account_id, target_name='friend', target_sec_uid='fixture-recipient', send_time='12:00', message_template='hello')
    assert client.post('/api/tasks', json={**body, 'target_sec_uid': ''}, headers=csrf).status_code == 400
    assert client.post('/api/tasks', json={**body, 'target_sec_uid': 'wrong-account'}, headers=csrf).status_code == 400
    created = client.post('/api/tasks', json=body, headers=csrf)
    assert created.status_code == 200, created.text
    task = created.json()
    tid = task['id']
    assert task['schedule_state'] == 'synced', task
    source = transport.sources[tid]
    assert source.event_bus_name == 'DouyinSpark-bus'
    assert source.source_scheduled_event_parameters.schedule == '0 0 12 * * *'
    assert source.source_scheduled_event_parameters.time_zone == 'GMT+8:00'
    assert json.loads(source.source_scheduled_event_parameters.user_data) == {'task_id': tid}
    service_headers = {'X-Service-Token': os.environ['SPARK_SERVICE_TOKEN'], 'X-Spark-Execution-Protocol': '3'}
    detail = client.get(f'/api/internal/scheduled-tasks/{tid}', headers=service_headers)
    assert detail.status_code == 200, detail.text
    assert detail.json()['params'] == {'spark_task_id': tid} and detail.json()['enabled']
    # A failure response in an HTTP-success envelope must not fall through to create.
    transport.fail = True
    calls_before = len([c for c in transport.calls if c[0] == 'create'])
    updated = client.put(f'/api/tasks/{tid}', json={**body, 'send_time': '13:00'}, headers=csrf)
    assert updated.status_code == 200 and updated.json()['schedule_state'] == 'error', updated.text
    assert '云权限不足' in updated.json()['schedule_error']
    assert len([c for c in transport.calls if c[0] == 'create']) == calls_before
    assert client.get(f'/api/internal/scheduled-tasks/{tid}', headers=service_headers).json()['enabled'] is False
    assert client.post(f'/api/tasks/{tid}/sync').status_code == 403
    transport.fail = False
    synced = client.post(f'/api/tasks/{tid}/sync', headers=csrf)
    assert synced.json()['schedule_state'] == 'synced', synced.text
    assert transport.sources[tid].source_scheduled_event_parameters.schedule == '0 0 13 * * *'
    from execution_scenario import check_executions
    from schedule_queue_scenario import check_queue
    client.portal.call(check_queue, tid)
    check_executions(client, service_headers, tid)
    paused = client.post(f'/api/tasks/{tid}/toggle', headers=csrf)
    assert not paused.json()['enabled'] and paused.json()['next_run_at'] is None
    assert tid not in transport.sources
    assert client.post(f'/api/tasks/{tid}/toggle', headers=csrf).json()['enabled']
    transport.fail = True
    removed = client.delete(f'/api/tasks/{tid}', headers=csrf)
    assert removed.status_code == 409
    assert client.put(f'/api/tasks/{tid}', json=body, headers=csrf).status_code == 409
    assert client.post(f'/api/tasks/{tid}/toggle', headers=csrf).status_code == 409
    assert client.get(f'/api/tasks/{tid}').json()['enabled'] is False
    assert client.get(f'/api/internal/scheduled-tasks/{tid}', headers=service_headers).json()['enabled'] is False
    transport.fail = False
    assert client.delete(f'/api/tasks/{tid}', headers=csrf).status_code == 200
    assert tid not in transport.sources
    assert client.get(f'/api/internal/scheduled-tasks/{tid}', headers=service_headers).status_code == 404
    print('Task CRUD, persisted config, execution mapping, failure recovery and delete: PASS')
