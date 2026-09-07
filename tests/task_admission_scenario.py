"""Concurrent writers must not jointly consume one remaining quota or time slot."""
import asyncio
from unittest.mock import patch
from core.db.models import User, DouyinAccount, DouyinContactIdentity, SparkTask, SparkTaskTargetIdentity, TaskQuotaGrant
from core.services.accounts import AccountService
from core.services.tasks import TaskService
from core.services.task_capacity import TaskCapacityService
from core.services import ValidationError, task_scheduling
from core.timeutil import utcnow


async def check_admission():
    service = TaskService(AccountService(None))  # No cookie operation in these tests.
    admin = await User.create(username='admission-admin', password_hash='unused', role='admin')
    user = await User.create(username='admission-user', password_hash='unused')
    accounts = {}
    for owner in (admin, user):
        account = await DouyinAccount.create(owner_user_id=owner.id, display_name='fixture', encrypted_cookies=b'x', cookie_nonce=b'x')
        await DouyinContactIdentity.create(account_id=account.id, sec_uid='friend-id', nickname='friend')
        accounts[owner.id] = account.id
    await TaskQuotaGrant.create(user_id=user.id, amount=1, starts_at=utcnow(), label='fixture', is_initial=True)
    async def remote(_): pass
    original_slot = TaskCapacityService.assert_slot_available
    async def slow_slot(self, *args):
        await original_slot(self, *args)
        # Widen the check/write gap: without the shared transaction both pass.
        await asyncio.sleep(0.03)
    async def create(owner, name, time):
        return await service.create(owner.id, accounts[owner.id], name, time, 'fixture-message', 'friend-id')
    def one_winner(results):
        assert sum(isinstance(result, SparkTask) for result in results) == 1, results
        assert sum(isinstance(result, ValidationError) for result in results) == 1, results
    with patch.object(task_scheduling, '_dispatch', remote), patch.object(TaskCapacityService, 'assert_slot_available', slow_slot):
        # Circular midnight distance must also hold under concurrent creation.
        result = await asyncio.gather(create(admin, 'left', '23:59'), create(admin, 'right', '00:01'), return_exceptions=True)
        one_winner(result)
        # Different free slots still share the same user's last quota.
        result = await asyncio.gather(create(user, 'left', '07:00'), create(user, 'right', '07:10'), return_exceptions=True)
        one_winner(result)
        first = next(task for task in result if isinstance(task, SparkTask))
        await service.set_enabled(first, False, user.id)
        second = await SparkTask.create(owner_user_id=user.id, douyin_account_id=accounts[user.id], target_name='paused', send_time='07:30', message_template='fixture', enabled=False)
        await SparkTaskTargetIdentity.create(task_id=second.id, sec_uid='friend-id')
        result = await asyncio.gather(service.set_enabled(first, True, user.id), service.set_enabled(second, True, user.id), return_exceptions=True)
        one_winner(result)
        assert await SparkTask.filter(owner_user_id=user.id, enabled=True).count() == 1
        # Concurrent edits cannot move two active tasks into one safety window.
        a, b = await create(admin, 'edit-left', '08:00'), await create(admin, 'edit-right', '08:10')
        result = await asyncio.gather(*[
            service.update_owned(admin.id, task.id, accounts[admin.id], task.target_name, time, 'fixture', 'friend-id')
            for task, time in ((a, '09:00'), (b, '09:01'))
        ], return_exceptions=True)
        one_winner(result)
    print('Task admission: concurrent midnight slots, quota, enable and edit PASS')
