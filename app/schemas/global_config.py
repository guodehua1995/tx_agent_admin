from typing import Optional

from pydantic import BaseModel, Field


class GlobalConfigCreate(BaseModel):
    config_key: str = Field(..., description="配置键")
    config_value: str = Field("", description="配置值")
    config_group: str = Field("default", description="配置分组")
    description: Optional[str] = Field(None, description="配置描述")


class GlobalConfigUpdate(BaseModel):
    id: int
    config_key: Optional[str] = None
    config_value: Optional[str] = None
    config_group: Optional[str] = None
    description: Optional[str] = None


class GlobalConfigItemUpdate(BaseModel):
    id: int = Field(..., description="配置ID")
    config_value: str = Field(..., description="配置值")


class GlobalConfigBatchUpdate(BaseModel):
    items: list[GlobalConfigItemUpdate] = Field(..., description="批量更新项")
