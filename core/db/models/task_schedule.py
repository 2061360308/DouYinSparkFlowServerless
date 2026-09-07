"""调度同步结果；业务任务和执行结果仍由原有模型负责。"""
from tortoise import fields, models


class ScheduleJob(models.Model):
    """Durable desired state, lease and retry clock; survives business deletion."""
    task_id = fields.CharField(max_length=36, primary_key=True)
    revision = fields.IntField(default=0)
    desired = fields.JSONField(default=dict)
    delete_requested = fields.BooleanField(default=False)
    lease_token = fields.CharField(max_length=64, default='')
    lease_until = fields.DatetimeField(null=True)
    next_attempt_at = fields.DatetimeField()
    attempts = fields.IntField(default=0)

    class Meta:
        table = 'schedule_jobs'


class TaskSchedule(models.Model):
    task_id = fields.CharField(max_length=36, primary_key=True)
    state = fields.CharField(max_length=16, default='pending')
    error = fields.CharField(max_length=240, default='')
    updated_at = fields.DatetimeField(auto_now=True)

    class Meta:
        table = 'task_schedule_sync'
