"""续火任务及执行记录模型。"""

from __future__ import annotations

from tortoise import fields, models

from .base import uuid_string


class SparkTask(models.Model):
    id = fields.CharField(max_length=36, primary_key=True, default=uuid_string)
    owner_user = fields.ForeignKeyField(
        "models.User", related_name="tasks",
        on_delete=fields.CASCADE, db_index=True,
    )
    douyin_account = fields.ForeignKeyField(
        "models.DouyinAccount", related_name="tasks",
        on_delete=fields.SET_NULL, null=True, db_index=True,
    )
    target_name = fields.CharField(max_length=64)
    send_time = fields.CharField(max_length=5)
    message_template = fields.CharField(max_length=500)
    enabled = fields.BooleanField(default=True)
    next_run_at = fields.DatetimeField(null=True, db_index=True)
    created_at = fields.DatetimeField(auto_now_add=True)
    updated_at = fields.DatetimeField(auto_now=True)

    class Meta:
        table = "spark_tasks"
        # 启用中的 (账号,目标,时间) 唯一：部分唯一索引 WHERE enabled 在 init 补建


class SparkTaskTargetIdentity(models.Model):
    task = fields.OneToOneField(
        "models.SparkTask", related_name="target_identity",
        on_delete=fields.CASCADE, primary_key=True,
    )
    sec_uid = fields.CharField(max_length=256)
    created_at = fields.DatetimeField(auto_now_add=True)

    class Meta:
        table = "spark_task_target_identities"


class TaskRun(models.Model):
    id = fields.CharField(max_length=36, primary_key=True, default=uuid_string)
    task = fields.ForeignKeyField(
        "models.SparkTask", related_name="runs",
        on_delete=fields.CASCADE, db_index=True,
    )
    scheduled_for = fields.DatetimeField()
    status = fields.CharField(max_length=16, default="queued")
    stage = fields.CharField(max_length=24, default="queued")
    started_at = fields.DatetimeField(null=True)
    finished_at = fields.DatetimeField(null=True)
    error_code = fields.CharField(max_length=48, null=True)
    error_summary = fields.CharField(max_length=240, null=True)
    message_digest = fields.CharField(max_length=64, null=True)

    class Meta:
        table = "task_runs"
        unique_together = (("task", "scheduled_for"),)
