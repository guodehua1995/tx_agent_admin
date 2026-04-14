from typing import Optional

from pydantic import BaseModel, Field


class LLMProviderConfigCreate(BaseModel):
    name: str = Field(..., description="显示名")
    provider_type: str = Field(..., description="提供商类型")
    api_base_url: str = Field(..., description="API地址")
    api_key: str = Field(..., description="API密钥")
    model_name: str = Field(..., description="模型标识")
    is_embedding: bool = Field(False, description="是否为Embedding模型")
    embedding_dimension: Optional[int] = Field(None, description="向量维度")
    max_tokens: int = Field(4096, description="最大token数")
    is_active: bool = Field(True, description="是否启用")
    extra_config: Optional[dict] = Field(None, description="额外参数")


class LLMProviderConfigUpdate(BaseModel):
    id: int
    name: Optional[str] = None
    provider_type: Optional[str] = None
    api_base_url: Optional[str] = None
    api_key: Optional[str] = None
    model_name: Optional[str] = None
    is_embedding: Optional[bool] = None
    embedding_dimension: Optional[int] = None
    max_tokens: Optional[int] = None
    is_active: Optional[bool] = None
    extra_config: Optional[dict] = None
