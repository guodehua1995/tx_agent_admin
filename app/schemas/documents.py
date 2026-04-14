from typing import Optional

from pydantic import BaseModel, Field


class DocumentTypeCreate(BaseModel):
    name: str = Field(..., description="类型名")
    code: str = Field(..., description="机器码")
    needs_structuring: bool = Field(False, description="是否需要AI结构化")
    is_active: bool = Field(True, description="是否启用")
    description: Optional[str] = Field(None, description="描述")


class DocumentTypeUpdate(BaseModel):
    id: int
    name: Optional[str] = None
    code: Optional[str] = None
    needs_structuring: Optional[bool] = None
    is_active: Optional[bool] = None
    description: Optional[str] = None


class DocumentCreate(BaseModel):
    title: str = Field(..., description="文档标题")
    source_type: str = Field(..., description="来源类型")
    source_meta: Optional[dict] = Field(None, description="来源元数据")
    doc_type_id: int = Field(..., description="文档类型ID")
    knowledge_base_id: int = Field(..., description="知识库ID")


class DocumentUpdate(BaseModel):
    id: int
    title: Optional[str] = None
    source_meta: Optional[dict] = None
    doc_type_id: Optional[int] = None
    knowledge_base_id: Optional[int] = None
