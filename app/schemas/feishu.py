from typing import Optional

from pydantic import BaseModel, Field


class FeishuBotConfigCreate(BaseModel):
    name: str = Field(..., description="机器人名称")
    app_id: str = Field(..., description="飞书应用ID")
    app_secret: str = Field(..., description="飞书应用密钥")
    verification_token: Optional[str] = Field(None, description="事件验证token")
    encrypt_key: Optional[str] = Field(None, description="事件加密key")
    agent_id: int = Field(..., description="绑定Agent ID")
    is_active: bool = Field(True, description="是否启用")


class FeishuBotConfigUpdate(BaseModel):
    id: int
    name: Optional[str] = None
    app_id: Optional[str] = None
    app_secret: Optional[str] = None
    verification_token: Optional[str] = None
    encrypt_key: Optional[str] = None
    agent_id: Optional[int] = None
    is_active: Optional[bool] = None


class FeishuWebhookEvent(BaseModel):
    challenge: Optional[str] = None
    token: Optional[str] = None
    type: Optional[str] = None
    schema_version: Optional[str] = Field(None, alias="schema")
    header: Optional[dict] = None
    event: Optional[dict] = None
