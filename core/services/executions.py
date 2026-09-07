"""At-most-one attempt per business task and schedule occurrence.

DB owns admission and the irreversible send boundary. A lost response never
grants permission to resend. Expired attempts are visible, never re-leased.
"""
import hashlib
import secrets
from datetime import datetime, timedelta, timezone
from zoneinfo import ZoneInfo

from core.db.transactions import write_transaction as in_transaction
from tortoise.expressions import Subquery
from core.db.models import ScheduledTask, SparkTask, SparkTaskTargetIdentity, TaskRun
from core.db.models.execution import ExecutionClaim, ExecutionEvidence
from core.services import Conflict, NotFound, ValidationError
from core.services.task_scheduling import schedule_status
from core.task.crud import compute_next_run
from core.task.execution_contract import message_fingerprint
from core.timeutil import utcnow

MAX_AGE = timedelta(minutes=10)
SHANGHAI = ZoneInfo('Asia/Shanghai')
TERMINAL = {'success', 'accepted', 'submitted', 'uncertain', 'failed'}


async def _digest(task):
    binding = await SparkTaskTargetIdentity.get_or_none(task_id=task.id)
    return message_fingerprint({'account_id': task.douyin_account_id, 'target_name': task.target_name,
                                'target_sec_uid': binding.sec_uid if binding else '',
                                'message_template': task.message_template, 'send_time': task.send_time})


async def _active(task):
    owner = await task.owner_user
    return bool(task.enabled and task.douyin_account_id and owner.status == 'active'
                and (await schedule_status(task))['schedule_state'] == 'synced')


def _slot(task, supplied, now):
    if supplied:
        try:
            event = datetime.fromisoformat(supplied.replace('Z', '+00:00'))
            if event.tzinfo is None:
                raise ValueError()
            slot = event.astimezone(timezone.utc).replace(tzinfo=None, second=0, microsecond=0)
        except (ValueError, TypeError):
            raise ValidationError('计划时间必须是带时区的 ISO 时间') from None
    else:
        local = now.replace(tzinfo=timezone.utc).astimezone(SHANGHAI)
        hour, minute = map(int, task.send_time.split(':'))
        slot = local.replace(hour=hour, minute=minute, second=0, microsecond=0)
        if slot > local:
            slot -= timedelta(days=1)
        slot = slot.astimezone(timezone.utc).replace(tzinfo=None)
    if slot.replace(tzinfo=timezone.utc).astimezone(SHANGHAI).strftime('%H:%M') != task.send_time:
        raise Conflict('旧计划时间已失效，不执行')
    if slot > now or now - slot > MAX_AGE:
        raise Conflict('已超过本次计划的执行窗口，不补发旧消息')
    return slot


async def claim(task_id: str, scheduled_for: str | None):
    async with in_transaction():
        scheduled = await ScheduledTask.filter(task_id=task_id).select_for_update().first()
        if not scheduled or scheduled.event_category != 'douyin_spark':
            raise NotFound('scheduled task not found')
        task = await SparkTask.get_or_none(id=(scheduled.params or {}).get('spark_task_id'))
        if not task or not scheduled.enabled or not await _active(task):
            raise Conflict('任务未启用或调度未同步')
        now = utcnow()
        slot = _slot(task, scheduled_for, now)
        # Legacy workers used actual execution timestamps. Preserve those attempts on upgrade.
        legacy = await TaskRun.filter(task_id=task.id, scheduled_for__gte=slot,
                                      scheduled_for__lt=slot + MAX_AGE).first()
        if legacy:
            return {'claimed': False, 'run_id': legacy.id, 'status': legacy.status}
        run, created = await TaskRun.get_or_create(task_id=task.id, scheduled_for=slot, defaults={
            'status': 'running', 'stage': 'preparing', 'started_at': now, 'message_digest': await _digest(task),
        })
        if not created:
            return {'claimed': False, 'run_id': run.id, 'status': run.status}
        token = secrets.token_urlsafe(32)
        await ExecutionClaim.create(run_id=run.id, token_hash=hashlib.sha256(token.encode()).hexdigest())
        binding = await SparkTaskTargetIdentity.get_or_none(task_id=task.id)
        await ExecutionEvidence.create(run_id=run.id, recipient_uid=binding.sec_uid if binding else '', account_id=task.douyin_account_id or '')
        scheduled.status = 'running'
        await scheduled.save(update_fields=['status', 'updated_at'])
        return {'claimed': True, 'run_id': run.id, 'token': token, 'message_digest': run.message_digest, 'scheduled_for': slot.isoformat() + 'Z'}


async def _owned(run_id, token):
    run = await TaskRun.filter(id=run_id).select_for_update().first()
    ownership = await ExecutionClaim.get_or_none(run_id=run_id)
    if not run or not ownership or not secrets.compare_digest(ownership.token_hash, hashlib.sha256(token.encode()).hexdigest()):
        raise NotFound('execution not found')
    return run


async def begin_send(run_id: str, token: str, message_digest: str):
    async with in_transaction():
        run = await _owned(run_id, token)
        if run.status != 'running' or run.stage != 'preparing':
            raise Conflict('发送权已使用或执行已结束，不可重复发送')
        task = await SparkTask.get(id=run.task_id)
        if message_digest != run.message_digest or utcnow() - run.started_at > MAX_AGE or not await _active(task) or await _digest(task) != run.message_digest:
            raise Conflict('任务已变更、暂停或执行超时，不发送')
        run.stage = 'sending'
        await run.save(update_fields=['stage'])
        return {'ok': True}


async def finish(run_id: str, token: str, status: str, reason: str = ''):
    if status not in TERMINAL:
        raise ValidationError('未知执行结果')
    async with in_transaction():
        run = await _owned(run_id, token)
        if run.status in TERMINAL:
            return {'status': run.status}
        evidence = await ExecutionEvidence.get_or_none(run_id=run.id)
        if status == 'success' and (not evidence or evidence.level not in {'delivered', 'read'}):
            raise Conflict('缺少匹配的服务端送达回执，不能标记成功')
        if status == 'accepted' and (not evidence or evidence.level not in {'accepted', 'delivered', 'read'}):
            raise Conflict('缺少匹配的服务端接收回执')
        if run.stage == 'sending' and status == 'failed':
            status = 'uncertain'
        if run.stage != 'sending' and status in {'success', 'accepted', 'submitted'}:
            raise Conflict('尚未取得发送权，不能标记发送成功')
        run.status, run.finished_at = status, utcnow()
        run.error_code = status if status in {'failed', 'uncertain'} else None
        run.error_summary = reason[:240] or None
        run.stage = {'success': 'confirmed', 'accepted': 'accepted', 'submitted': 'submitted', 'uncertain': 'confirming', 'failed': 'preparing'}[status]
        await run.save()
        scheduled = await ScheduledTask.get_or_none(task_id=run.task_id)
        if scheduled:
            # A delayed older result cannot overwrite the latest execution summary.
            newer = await TaskRun.filter(task_id=run.task_id, scheduled_for__gt=run.scheduled_for).exists()
            if not newer:
                scheduled.status, scheduled.last_run_at = status, run.finished_at
                scheduled.next_run_at = compute_next_run(scheduled.cron_expr) if scheduled.enabled else None
                await scheduled.save(update_fields=['status', 'last_run_at', 'next_run_at', 'updated_at'])
        return {'status': status}


async def record_receipt(run_id: str, token: str, receipt: dict):
    """Trusted worker adapter boundary, not a parser for unverified Douyin payloads.

    Only an adapter with a verified provider contract may normalize receipts.
    Current DOM executor has no such adapter and never calls this endpoint.
    """
    levels = {'accepted': 1, 'delivered': 2, 'read': 3}
    if receipt['level'] not in levels or receipt['source'] != 'douyin_verified_adapter_v1':
        raise ValidationError('不支持的送达证据来源或状态')
    async with in_transaction():
        run = await _owned(run_id, token)
        evidence = await ExecutionEvidence.get_or_none(run_id=run.id)
        if not evidence or not evidence.recipient_uid or evidence.recipient_uid != receipt['recipient_uid'] or run.message_digest != receipt['message_digest']:
            raise Conflict('回执与执行收件人或消息不匹配')
        if run.stage == 'preparing' or run.status == 'failed':
            raise Conflict('未进入发送阶段，不能接收回执')
        observed = receipt['observed_at']
        if observed.tzinfo is None:
            raise ValidationError('回执时间必须包含时区')
        observed = observed.astimezone(timezone.utc).replace(tzinfo=None)
        if observed < run.started_at or observed > utcnow() + timedelta(seconds=30):
            raise Conflict('回执时间不在有效范围')
        if evidence.message_id and (evidence.message_id != receipt['message_id'] or evidence.conversation_id != receipt['conversation_id']):
            raise Conflict('一次执行不能绑定多个服务端消息')
        if levels[receipt['level']] <= levels.get(evidence.level, 0):
            return {'status': run.status, 'delivery_level': evidence.level}
        if evidence.observed_at and observed < evidence.observed_at:
            raise Conflict('回执时间早于已保存证据，不能升级状态')
        import json
        message_key = hashlib.sha256(json.dumps([evidence.account_id, receipt['conversation_id'], receipt['message_id']]).encode()).hexdigest()
        if await ExecutionEvidence.filter(message_key=message_key).exclude(run_id=run.id).exists():
            raise Conflict('此服务端消息已归属于其他执行')
        evidence.level = receipt['level']
        evidence.message_id, evidence.conversation_id = receipt['message_id'], receipt['conversation_id']
        evidence.source, evidence.observed_at, evidence.message_key = receipt['source'], observed, message_key
        await evidence.save()
        run.status = 'accepted' if evidence.level == 'accepted' else 'success'
        run.stage = 'accepted' if evidence.level == 'accepted' else 'confirmed'
        run.error_code = None
        run.error_summary = {'accepted': '服务端已接收，尚无送达回执。', 'delivered': '已收到匹配的送达回执，未确认已读。', 'read': '已收到匹配的已读回执。'}[evidence.level]
        run.finished_at = utcnow()
        await run.save()
        if not await TaskRun.filter(task_id=run.task_id, scheduled_for__gt=run.scheduled_for).exists():
            await ScheduledTask.filter(task_id=run.task_id).update(status=run.status, last_run_at=run.finished_at)
        return {'status': run.status, 'delivery_level': evidence.level}


async def expire_runs(owner_id: str | None = None):
    """Conservative timeout accounting, not permission to execute again."""
    query = TaskRun.filter(status='running', started_at__lt=utcnow() - MAX_AGE,
                           id__in=Subquery(ExecutionClaim.all().values('run_id')))
    if owner_id:
        query = query.filter(task__owner_user_id=owner_id)
    ids = await query.values_list('id', flat=True)
    # Select scoped IDs first: SQLite does not support Tortoise's joined UPDATE form.
    expired = TaskRun.filter(id__in=ids, status='running', started_at__lt=utcnow() - MAX_AGE)
    await expired.filter(stage='preparing').update(status='failed', finished_at=utcnow(), error_code='execution_timeout', error_summary='执行器超时，未进入发送阶段；本次不会自动重试。')
    await expired.filter(stage='sending').update(status='uncertain', finished_at=utcnow(), error_code='confirmation_missing', error_summary='发送阶段未收到结果，请核实聊天记录；不会自动重发。')
