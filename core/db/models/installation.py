"""Single installation record: durable ROS identity and encrypted submission payload."""
from tortoise import fields, models


class Installation(models.Model):
    id = fields.IntField(primary_key=True)
    request_hash = fields.CharField(max_length=64)
    client_token = fields.CharField(max_length=64)
    stack_id = fields.CharField(max_length=128, default='')
    status = fields.CharField(max_length=64, default='SUBMITTING')
    status_reason = fields.TextField(default='')
    ciphertext = fields.BinaryField()
    nonce = fields.BinaryField()
    outputs = fields.JSONField(default=dict)
    created_at = fields.DatetimeField(auto_now_add=True)

    class Meta:
        table = 'installation'
