"""Concurrency and restart tests on the isolated real database, fake remote I/O."""
import asyncio
import sys
import tempfile
from pathlib import Path
from datetime import timedelta
from unittest.mock import patch
from core.db.models import SparkTask, ScheduledTask
from core.db.models.task_schedule import ScheduleJob, TaskSchedule
from core.db.system_config_db import SystemConfigDB
from core.services import task_scheduling as s


async def check_queue(task_id):
    original = await SparkTask.get(id=task_id)
    entered, release = asyncio.Event(), asyncio.Event()
    calls = []

    async def slow(desired):
        calls.append(desired)
        entered.set()
        await release.wait()

    async def fast(desired):
        calls.append(desired)

    await s.enqueue(task_id)
    with patch.object(s, '_dispatch', slow):
        worker = asyncio.create_task(s.process_job(task_id))
        await entered.wait()
        # Remote I/O cannot hold a SQLite write lock; another write must complete.
        await asyncio.wait_for(SystemConfigDB.set_value('browser_concurrency', '4'), 1)
        assert not await s.process_job(task_id), 'two workers acquired the same lease'
        await SparkTask.filter(id=task_id).update(send_time='14:00')
        await s.enqueue(task_id)
        release.set()
        assert not await worker, 'stale revision acknowledged'
    assert not (await ScheduledTask.get(task_id=task_id)).enabled
    with patch.object(s, '_dispatch', fast):
        assert await s.process_job(task_id)
    assert (await TaskSchedule.get(task_id=task_id)).state == 'synced'
    assert calls[-1]['cron_expr'] == '0 14 * * *'

    # Simulate a paused old process waking after another worker reclaimed its lease.
    entered.clear()
    release.clear()
    await s.enqueue(task_id)
    with patch.object(s, '_dispatch', slow):
        old_worker = asyncio.create_task(s.process_job(task_id))
        await entered.wait()
        future = s.utcnow() + s.LEASE + timedelta(seconds=1)
        with patch.object(s, 'utcnow', lambda: future), patch.object(s, '_dispatch', fast):
            assert await s.process_job(task_id)
        release.set()
        assert not await old_worker
    assert (await TaskSchedule.get(task_id=task_id)).state == 'pending'
    assert not (await ScheduledTask.get(task_id=task_id)).enabled
    with patch.object(s, '_dispatch', fast):
        assert await s.process_job(task_id)

    # Death mid-call: durable lease remains, next process can claim only after expiry.
    entered.clear()
    release.clear()
    await s.enqueue(task_id)
    with patch.object(s, '_dispatch', slow):
        worker = asyncio.create_task(s.process_job(task_id))
        await entered.wait()
        worker.cancel()
        try:
            await worker
        except asyncio.CancelledError:
            pass
    assert (await ScheduleJob.get(task_id=task_id)).lease_token
    with patch.object(s, '_dispatch', fast):
        assert not await s.process_job(task_id)
        future = s.utcnow() + s.LEASE + timedelta(seconds=1)
        with patch.object(s, 'utcnow', lambda: future):
            assert await s.process_job(task_id)

    # A failed call persists backoff and is retried by a fresh reconciliation pass.
    await s.enqueue(task_id)
    async def fail(_): raise TimeoutError('private-response')
    with patch.object(s, '_dispatch', fail):
        assert not await s.process_job(task_id)
    job = await ScheduleJob.get(task_id=task_id)
    assert job.attempts == 1 and job.next_attempt_at > s.utcnow()
    with patch.object(s, '_dispatch', fast), patch.object(s, 'utcnow', lambda: job.next_attempt_at):
        assert (await s.reconcile())['completed'] >= 1
    # Recover business mutation committed just before the writer process died.
    await SparkTask.filter(id=task_id).update(send_time=original.send_time)
    with patch.object(s, '_dispatch', fast):
        assert (await s.reconcile())['completed'] >= 1
    assert (await ScheduledTask.get(task_id=task_id)).cron_expr == s.cron_for(original)
    await s.enqueue(task_id)
    with tempfile.TemporaryDirectory() as directory:
        record = Path(directory) / 'dispatches.txt'
        worker_script = Path(__file__).with_name('schedule_process_worker.py')
        children = await asyncio.gather(*[
            asyncio.create_subprocess_exec(sys.executable, str(worker_script), task_id, str(record),
                                           stdout=asyncio.subprocess.PIPE, stderr=asyncio.subprocess.PIPE)
            for _ in range(2)
        ])
        outputs = await asyncio.wait_for(asyncio.gather(*(child.communicate() for child in children)), 20)
        assert all(child.returncode == 0 for child in children), outputs
        assert record.read_text().splitlines() == ['dispatch'], outputs
    print('Durable queue: lock release, lease exclusion, stale completion, restart, backoff and writer gap PASS')
