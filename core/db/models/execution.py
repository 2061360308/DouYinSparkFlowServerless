"""Execution ownership for an existing unique TaskRun occurrence."""
from tortoise import fields, models


class ExecutionEvidence(models.Model):
    run = fields.OneToOneField('models.TaskRun', primary_key=True, related_name='delivery_evidence', on_delete=fields.CASCADE)
    recipient_uid = fields.CharField(max_length=256, default='')
    account_id = fields.CharField(max_length=36, default='')
    level = fields.CharField(max_length=16, default='unknown')
    message_id = fields.CharField(max_length=256, default='')
    conversation_id = fields.CharField(max_length=256, default='')
    source = fields.CharField(max_length=64, default='')
    observed_at = fields.DatetimeField(null=True)
    message_key = fields.CharField(max_length=64, unique=True, null=True)

    class Meta:
        table = 'execution_evidence'


class ExecutionClaim(models.Model):
    run = fields.OneToOneField('models.TaskRun', primary_key=True, related_name='execution_claim', on_delete=fields.CASCADE)
    token_hash = fields.CharField(max_length=64)

    class Meta:
        table = 'execution_claims'
