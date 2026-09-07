"""Persisted business task → scheduled task → platform trigger.

The database owns desired state and retry leases. Remote I/O runs outside DB
transactions; fenced completion cannot acknowledge an obsolete revision.
"""
import asyncio
import sys
import secrets
from datetime import timedelta

from core.db.transactions import write_transaction as in_transaction
from core.browser.manager import is_docker_deployment
from core.db.models import ScheduledTask, SparkTask
from core.db.models.task_schedule import TaskSchedule, ScheduleJob
from core.db.system_config_db import SystemConfigDB
from core.services import Conflict, ValidationError
from core.services.installation import installed_credentials
from core.task import dispatcher
from core.timeutil import utcnow

LEASE = timedelta(minutes=2)
RECONCILE_INTERVAL = timedelta(minutes=10)


class MissingScheduleConfig(Exception):
    pass


def sync_error(error: Exception) -> str:
    """Expose actionable categories, never SDK payloads, credentials or URLs."""
    code = getattr(error, 'code', '')
    if isinstance(error, MissingScheduleConfig):
        return '调度配置缺失：请管理员检查地域、事件总线和云凭据，然后重试同步。'
    if isinstance(error, ValidationError):
        return '云凭据读取失败：请管理员检查加密密钥及安装凭据，然后重试同步。'
    if code in {'AccessDenied', 'Forbidden', 'Forbidden.RAM', 'NoPermission'}:
        return '云权限不足：请管理员检查 EventBridge 事件源读写权限，然后重试同步。'
    if code in {'InvalidAccessKeyId', 'InvalidAccessKeyId.NotFound', 'SignatureDoesNotMatch'}:
        return '云身份验证失败：请管理员检查当前生效的 AK/SK，然后重试同步。'
    if code in {'Throttling', 'Throttling.User', 'Throttling.Api', 'ServiceUnavailable', 'InternalError'}:
        return '云服务限流或暂不可用，请稍后重试同步。'
    if isinstance(error, (TimeoutError, ConnectionError)):
        return '连接调度服务超时或中断，结果尚未确认；请重试同步，执行入口保持关闭。'
    if isinstance(error, FileNotFoundError):
        return '本机调度程序不可用，请管理员检查系统任务调度工具是否安装。'
    return '调度未同步，请检查部署配置、云权限或调度服务后重试。任务已保存。'


async def _dispatch(task: dict):
    if task['target_env'] != 'fc':
        await asyncio.to_thread(dispatcher.sync, task)
        return
    config = await SystemConfigDB.get_many([
        'region', 'eventbridge_bus_name', 'platform_access_key_id', 'platform_access_key_secret',
    ])
    config.update(await installed_credentials())
    if not all(config.values()):
        raise MissingScheduleConfig()
    client = dispatcher._eb_client(config)
    if task['enabled']:
        await asyncio.to_thread(dispatcher.register_fc, task, client=client, bus_name=config['eventbridge_bus_name'], time_zone='GMT+8:00')
    else:
        await asyncio.to_thread(dispatcher.unregister_fc, task['task_id'], client=client, bus_name=config['eventbridge_bus_name'])


def cron_for(task: SparkTask) -> str:
    hour, minute = map(int, task.send_time.split(':'))
    return f'{minute} {hour} * * *'


def desired_state(task):
    env = ('windows' if sys.platform == 'win32' else 'linux') if is_docker_deployment() else 'fc'
    return {'task_id': task.id, 'cron_expr': cron_for(task), 'event_category': 'douyin_spark',
            'params': {'spark_task_id': task.id}, 'target_env': env, 'enabled': task.enabled}


async def lock_for_change(task_id):
    """Call inside the business write transaction; keep job-before-task lock order."""
    await ScheduleJob.get_or_create(task_id=task_id, defaults={'next_attempt_at': utcnow()})
    job = await ScheduleJob.filter(task_id=task_id).select_for_update().get()
    if job.delete_requested:
        raise Conflict('任务正在删除并清理调度器，不能修改或重新启用')


async def enqueue(task_id: str, *, delete: bool = False):
    # A delete intent is sticky; later edits may not resurrect its remote trigger.
    async with in_transaction():
        task = await SparkTask.get_or_none(id=task_id)
        if task is None:
            return
        await ScheduleJob.get_or_create(task_id=task_id, defaults={'next_attempt_at': utcnow()})
        job = await ScheduleJob.filter(task_id=task_id).select_for_update().get()
        job.delete_requested = job.delete_requested or delete
        if job.delete_requested:
            task.enabled = False
            task.next_run_at = None
            await task.save(update_fields=['enabled', 'next_run_at', 'updated_at'])
        desired = desired_state(task)
        job.desired = desired
        job.revision += 1
        job.attempts = 0
        job.next_attempt_at = utcnow()
        await job.save()
        await TaskSchedule.update_or_create(task_id=task_id, defaults={'state': 'pending', 'error': ''})
        await ScheduledTask.update_or_create(task_id=task.id, defaults={
            **{k: v for k, v in desired.items() if k != 'task_id'}, 'enabled': False,
            'next_run_at': task.next_run_at if task.enabled else None,
        })


async def process_job(task_id: str) -> bool:
    async with in_transaction():
        job = await ScheduleJob.filter(task_id=task_id).select_for_update().first()
        now = utcnow()
        if not job or job.next_attempt_at > now or (job.lease_token and job.lease_until > now):
            return False
        if not await SparkTask.exists(id=task_id) and not job.delete_requested:
            job.delete_requested = True
            job.desired = {**job.desired, 'enabled': False}
            job.revision += 1
        token = secrets.token_hex(24)
        job.lease_token, job.lease_until = token, now + LEASE
        await job.save()
        revision, desired, deleting = job.revision, dict(job.desired), job.delete_requested
    # No transaction or row lock is held over the network/subprocess boundary.
    error = None
    try:
        await _dispatch(desired)
    except Exception as exc:
        error = sync_error(exc)
    # Cancellation/crash intentionally leaves the lease for another process to recover.
    async with in_transaction():
        job = await ScheduleJob.filter(task_id=task_id).select_for_update().get()
        if job.lease_token != token:
            # A late external write can still happen; request a fresh reconciliation.
            job.next_attempt_at = utcnow()
            await job.save(update_fields=['next_attempt_at'])
            await ScheduledTask.filter(task_id=task_id).update(enabled=False)
            if await SparkTask.exists(id=task_id):
                await TaskSchedule.update_or_create(task_id=task_id, defaults={'state': 'pending', 'error': '检测到过期同步结果，等待重新核对调度。'})
            return False
        job.lease_token, job.lease_until = '', None
        task = await SparkTask.get_or_none(id=task_id)
        stale = job.revision != revision or (task and desired_state(task) != desired)
        if stale:
            job.next_attempt_at = utcnow()
            await job.save()
            if task:
                await TaskSchedule.update_or_create(task_id=task_id, defaults={'state': 'pending', 'error': ''})
            return False
        if error:
            job.attempts += 1
            job.next_attempt_at = utcnow() + timedelta(seconds=min(900, 30 * 2 ** min(job.attempts - 1, 5)))
            await ScheduledTask.filter(task_id=task_id).update(enabled=False)
            await TaskSchedule.update_or_create(task_id=task_id, defaults={'state': 'error', 'error': error})
        else:
            job.attempts = 0
            job.next_attempt_at = utcnow() + RECONCILE_INTERVAL
            if deleting:
                await ScheduledTask.filter(task_id=task_id).delete()
                await SparkTask.filter(id=task_id).delete()
                await TaskSchedule.filter(task_id=task_id).delete()
                # Keep the tombstone to remove late remote writes after lease recovery.
            elif task:
                await ScheduledTask.filter(task_id=task_id).update(enabled=task.enabled)
                await TaskSchedule.update_or_create(task_id=task_id, defaults={'state': 'synced', 'error': ''})
        await job.save()
        return error is None


async def reconcile(*, limit: int = 20) -> dict:
    # Repair the crash gap between an existing business writer and enqueue. The
    # business row remains authoritative; reads never start irreversible messages.
    for task in await SparkTask.all():
        job = await ScheduleJob.get_or_none(task_id=task.id)
        if not job or job.desired != desired_state(task):
            await enqueue(task.id)
    ids = await ScheduleJob.filter(next_attempt_at__lte=utcnow()).order_by('next_attempt_at').limit(limit).values_list('task_id', flat=True)
    completed = 0
    for task_id in ids:
        completed += bool(await process_job(task_id))
    return {'checked': len(ids), 'completed': completed}


async def sync_task(task_id: str, *, delete: bool = False) -> bool:
    await enqueue(task_id, delete=delete)
    return await process_job(task_id)


async def schedule_status(task: SparkTask) -> dict:
    sync = await TaskSchedule.get_or_none(task_id=task.id)
    scheduled = await ScheduledTask.get_or_none(task_id=task.id)
    state = sync.state if sync else 'pending'
    if state == 'synced' and (not scheduled or scheduled.enabled != task.enabled or scheduled.cron_expr != cron_for(task)):
        state = 'pending'
    return {'schedule_state': state, 'schedule_error': sync.error if sync else ''}


async def delete_task(task_id: str):
    # Commit the pause before any remote deletion; a process crash cannot re-enable it.
    await SparkTask.filter(id=task_id).update(enabled=False, next_run_at=None)
    if not await sync_task(task_id, delete=True):
        raise Conflict('任务已暂停，但调度器清理未成功；请重试删除。')
