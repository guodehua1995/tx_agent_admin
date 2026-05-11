from typing import Optional

from pydantic import BaseModel, Field


class DocumentCreate(BaseModel):
    title: str = Field(..., description="文档标题")
    source_type: str = Field(..., description="来源类型")
    source_meta: Optional[dict] = Field(None, description="来源元数据")
    doc_type_code: str = Field(..., description="文档类型编码")
    knowledge_base_id: int = Field(..., description="知识库ID")


class DocumentUpdate(BaseModel):
    id: int
    title: Optional[str] = None
    source_meta: Optional[dict] = None
    doc_type_code: Optional[str] = None
    knowledge_base_id: Optional[int] = None
    content: Optional[str] = None


class DocumentSubmitForReview(BaseModel):
    id: int = Field(..., description="文档ID")
    content: str = Field(..., description="文档内容")
