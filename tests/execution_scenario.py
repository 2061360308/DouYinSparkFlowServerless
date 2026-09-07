"""Real API/SQLite execution admission tests, called from isolated scheduling fixture."""
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timedelta
from core.services import executions
from core.db.models import SparkTask, TaskRun


def check_executions(client, headers, tid):
    original_clock = executions.utcnow
    clock = datetime(2026, 9, 7, 5, 0, 10)  # 13:00 Shanghai
    executions.utcnow = lambda: clock
    claim_url = f'/api/internal/scheduled-tasks/{tid}/claim'
    try:
        assert client.post(claim_url, json={}).status_code == 401
        assert client.get(f'/api/internal/scheduled-tasks/{tid}', headers={'X-Service-Token': headers['X-Service-Token']}).status_code == 409
        assert client.get(f'/api/internal/scheduled-tasks/{tid}', headers={**headers, 'X-Spark-Execution-Protocol': '2'}).status_code == 409
        assert client.post(claim_url, json={'scheduled_for': 'invalid'}, headers=headers).status_code == 400
        assert client.post(claim_url, json={'scheduled_for': '2026-09-07T06:00:00Z'}, headers=headers).status_code == 409
        body = {'scheduled_for': '2026-09-07T05:00:00Z'}
        with ThreadPoolExecutor(max_workers=2) as pool:
            results = list(pool.map(lambda _: client.post(claim_url, json=body, headers=headers), range(2)))
        assert all(r.status_code == 200 for r in results), [r.text for r in results]
        grants = [r.json() for r in results if r.json()['claimed']]
        assert len(grants) == 1, [r.json() for r in results]
        grant = grants[0]
        sending = f"/api/internal/executions/{grant['run_id']}/sending"
        finish = f"/api/internal/executions/{grant['run_id']}/finish"
        token = {'token': grant['token'], 'message_digest': grant['message_digest']}
        assert client.post(sending, json={**token, 'token': 'wrong' * 10}, headers=headers).status_code == 404
        assert client.post(sending, json={**token, 'message_digest': '0' * 64}, headers=headers).status_code == 409
        async def set_enabled(enabled):
            await SparkTask.filter(id=tid).update(enabled=enabled)
        client.portal.call(set_enabled, False)
        assert client.post(sending, json=token, headers=headers).status_code == 409
        client.portal.call(set_enabled, True)
        assert client.post(f'/api/internal/spark-tasks/{tid}/runs', json={'status': 'success'}, headers=headers).status_code == 410
        assert client.post(f'/api/internal/scheduled-tasks/{tid}/started', headers=headers).status_code == 409
        assert client.post(finish, json={**token, 'status': 'success'}, headers=headers).status_code == 409
        assert client.post(sending, json=token, headers=headers).status_code == 200
        assert client.post(sending, json=token, headers=headers).status_code == 409
        result = client.post(finish, json={**token, 'status': 'failed', 'reason': 'connection lost'}, headers=headers)
        assert result.json()['status'] == 'uncertain', result.text
        assert client.post(finish, json={**token, 'status': 'success'}, headers=headers).json()['status'] == 'uncertain'
        assert not client.post(claim_url, json=body, headers=headers).json()['claimed']
        async def run_count():
            return await TaskRun.filter(task_id=tid).count()
        assert client.portal.call(run_count) == 1
        # Next day's slot is independent; expiry never grants permission to replay.
        clock += timedelta(days=1)
        next_day = client.post(claim_url, json={}, headers=headers).json()
        assert next_day['claimed']
        clock += timedelta(minutes=11)
        client.portal.call(executions.expire_runs)
        late = client.post(f"/api/internal/executions/{next_day['run_id']}/sending", json={'token': next_day['token'], 'message_digest': next_day['message_digest']}, headers=headers)
        assert late.status_code == 409
        assert client.post(claim_url, json=body, headers=headers).status_code == 409
        clock += timedelta(days=1, minutes=-11)
        third = client.post(claim_url, json={}, headers=headers).json()
        third_token = {'token': third['token'], 'message_digest': third['message_digest']}
        assert client.post(f"/api/internal/executions/{third['run_id']}/sending", json=third_token, headers=headers).status_code == 200
        clock += timedelta(minutes=11)
        client.portal.call(executions.expire_runs)
        assert client.post(f"/api/internal/executions/{third['run_id']}/finish", json={**third_token, 'status': 'success'}, headers=headers).json()['status'] == 'uncertain'
        # Receipt pipeline: unknown evidence never becomes success; validated
        # normalized receipts may upgrade a finished uncertain attempt, never resend.
        from core.db.models import SparkTaskTargetIdentity
        async def bind():
            await SparkTaskTargetIdentity.update_or_create(task_id=tid, defaults={'sec_uid': 'fixture-recipient'})
        client.portal.call(bind)
        clock += timedelta(days=1, minutes=-11)
        fourth = client.post(claim_url, json={}, headers=headers).json()
        fourth_token = {'token': fourth['token'], 'message_digest': fourth['message_digest']}
        receipt_url = f"/api/internal/executions/{fourth['run_id']}/receipt"
        receipt = {**fourth_token, 'source': 'douyin_verified_adapter_v1', 'level': 'accepted',
                   'recipient_uid': 'fixture-recipient', 'message_id': 'provider-message-1',
                   'conversation_id': 'conversation-1', 'observed_at': clock.isoformat() + 'Z'}
        assert client.post(receipt_url, json=receipt, headers=headers).status_code == 409
        assert client.post(f"/api/internal/executions/{fourth['run_id']}/sending", json=fourth_token, headers=headers).status_code == 200
        assert client.post(f"/api/internal/executions/{fourth['run_id']}/finish", json={**fourth_token, 'status': 'success'}, headers=headers).status_code == 409
        assert client.post(receipt_url, json={**receipt, 'recipient_uid': 'wrong-user'}, headers=headers).status_code == 409
        assert client.post(receipt_url, json={**receipt, 'message_digest': '0' * 64}, headers=headers).status_code == 409
        assert client.post(receipt_url, json={**receipt, 'token': 'bad' * 16}, headers=headers).status_code == 404
        assert client.post(receipt_url, json={**receipt, 'source': 'dom-text'}, headers=headers).status_code == 422
        assert client.post(receipt_url, json=receipt, headers=headers).json()['status'] == 'accepted'
        assert client.post(receipt_url, json={**receipt, 'message_id': 'different-message'}, headers=headers).status_code == 409
        assert client.post(receipt_url, json={**receipt, 'level': 'delivered'}, headers=headers).json()['status'] == 'success'
        assert client.post(receipt_url, json=receipt, headers=headers).json()['delivery_level'] == 'delivered'
        assert client.post(receipt_url, json={**receipt, 'level': 'read'}, headers=headers).json()['delivery_level'] == 'read'
        assert not client.post(claim_url, json={}, headers=headers).json()['claimed']
    finally:
        executions.utcnow = original_clock
    print('Execution concurrency, token ownership, send boundary, uncertainty and expiry: PASS')
