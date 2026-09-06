"""调度同步结果；业务任务和执行结果仍由原有模型负责。"""
from tortoise import fields, models


class TaskSchedule(models.Model):
    task_id = fields.CharField(max_length=36, primary_key=True)
    state = fields.CharField(max_length=16, default='pending')
    error = fields.CharField(max_length=240, default='')
    updated_at = fields.DatetimeField(auto_now=True)

    class Meta:
        table = 'task_schedule_sync'
