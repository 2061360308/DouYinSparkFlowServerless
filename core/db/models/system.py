"""系统配置表模型。

系统配置采用 key-value 形式，便于运行时扩展而无需改表结构。
所有键在 ``core.db.config.SYSTEM_CONFIG_KEYS`` 中注册默认值。
"""

from tortoise import fields, models


class SystemSecret(models.Model):
    key = fields.CharField(max_length=100, primary_key=True)
    ciphertext = fields.BinaryField()
    nonce = fields.BinaryField()

    class Meta:
        table = 'system_secrets'


class SystemConfig(models.Model):
    """系统配置表（key-value 形式）。"""

    id = fields.IntField(primary_key=True)
    config_key = fields.CharField(
        max_length=100, unique=True, description="配置键，如 browser_concurrency"
    )
    config_value = fields.TextField(description="配置值")
    created_at = fields.DatetimeField(auto_now_add=True, description="创建时间")
    updated_at = fields.DatetimeField(auto_now=True, description="更新时间")

    class Meta:
        table = "system_config"
        ordering = ["id"]

    @classmethod
    async def get_int(cls, key: str, default: int = 0) -> int:
        """按配置键读取整数值，便于应用代码使用。"""
        row = await cls.get_or_none(config_key=key)
        if row is None:
            return default
        try:
            return int(row.config_value)
        except ValueError:
            return default
