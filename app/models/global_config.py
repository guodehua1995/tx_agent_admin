from tortoise import fields

from .base import BaseModel, TimestampMixin


class GlobalConfig(BaseModel, TimestampMixin):
    config_key = fields.CharField(max_length=200, unique=True, description="配置键")
    config_value = fields.TextField(default="", description="配置值")
    config_group = fields.CharField(max_length=100, default="default", description="配置分组", index=True)
    description = fields.CharField(max_length=500, null=True, description="配置描述")

    class Meta:
        table = "global_config"
