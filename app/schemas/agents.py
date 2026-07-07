from typing import Optional

from pydantic import BaseModel, Field


class AgentCreate(BaseModel):
    name: str = Field(..., description="Agent名称")
    code: Optional[str] = Field(None, description="路由标识，对应 AgentRegistry 中的 agent name")
    description: Optional[str] = Field(None, description="描述")
    is_active: bool = Field(True, description="是否启用")


class AgentUpdate(BaseModel):
    id: int
    name: Optional[str] = None
    code: Optional[str] = None
    description: Optional[str] = None
    is_active: Optional[bool] = None
