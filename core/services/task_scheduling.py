"""Persisted business task → scheduled task → platform trigger.

The sync row serializes platform writes across processes. Failed requests keep a
disabled execution projection and an explicit retry state, never a fake success.
"""
import asyncio
import sys

from tortoise.transactions import in_transaction
from core.browser.manager import is_docker_deployment
from core.db.models import ScheduledTask, SparkTask
from core.db.models.task_schedule import TaskSchedule
from core.db.system_config_db import SystemConfigDB
from core.services import Conflict
from core.services.installation import installed_credentials
from core.task import dispatcher


async def _dispatch(task: dict):
    if task['target_env'] != 'fc':
        await asyncio.to_thread(dispatcher.sync, task)
        return
    config = await SystemConfigDB.get_many([
        'region', 'eventbridge_bus_name', 'platform_access_key_id', 'platform_access_key_secret',
    ])
    config.update(await installed_credentials())
    if not all(config.values()):
        raise ValueError('cloud configuration missing')
    client = dispatcher._eb_client(config)
    if task['enabled']:
        await asyncio.to_thread(dispatcher.register_fc, task, client=client, bus_name=config['eventbridge_bus_name'], time_zone='GMT+8:00')
    else:
        await asyncio.to_thread(dispatcher.unregister_fc, task['task_id'], client=client, bus_name=config['eventbridge_bus_name'])


def cron_for(task: SparkTask) -> str:
    hour, minute = map(int, task.send_time.split(':'))
    return f'{minute} {hour} * * *'


async def sync_task(task_id: str, *, delete: bool = False) -> bool:
    await TaskSchedule.get_or_create(task_id=task_id)
    async with in_transaction():
        sync = await TaskSchedule.filter(task_id=task_id).select_for_update().get()
        task = await SparkTask.get_or_none(id=task_id)
        if task is None:
            return False
        if delete:
            task.enabled = False
            task.next_run_at = None
            await task.save(update_fields=['enabled', 'next_run_at', 'updated_at'])
        env = ('windows' if sys.platform == 'win32' else 'linux') if is_docker_deployment() else 'fc'
        desired = {'task_id': task.id, 'cron_expr': cron_for(task), 'event_category': 'douyin_spark',
                   'params': {'spark_task_id': task.id}, 'target_env': env, 'enabled': task.enabled}
        # Execution stays disabled if external synchronization fails or times out.
        scheduled, _ = await ScheduledTask.update_or_create(task_id=task.id, defaults={
            **{k: v for k, v in desired.items() if k != 'task_id'}, 'enabled': False,
            'next_run_at': task.next_run_at if task.enabled else None,
        })
        try:
            await _dispatch(desired)
        except Exception:
            sync.state = 'error'
            sync.error = '调度未同步，请检查部署配置、云权限或调度服务后重试。任务已保存。'
        else:
            scheduled.enabled = task.enabled
            await scheduled.save(update_fields=['enabled', 'updated_at'])
            sync.state, sync.error = 'synced', ''
            if delete:
                await scheduled.delete()
                await task.delete()
        await sync.save(update_fields=['state', 'error', 'updated_at'])
        if delete and sync.state == 'synced':
            await sync.delete()
        return sync.state == 'synced'


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
