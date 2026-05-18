from typing import Optional

from pydantic import BaseModel, Field


class PageEditItem(BaseModel):
    page_number: int = Field(..., description="页码")
    content: str = Field(..., description="编辑后的页面内容")


class ReviewSubmit(BaseModel):
    document_id: int = Field(..., description="文档ID")
    action: str = Field(..., description="审核动作: approve/reject")
    comment: Optional[str] = Field(None, description="审核意见")
    edited_content: Optional[str] = Field(None, description="整文档编辑后内容（非分页文档使用）")
    page_edits: Optional[list[PageEditItem]] = Field(None, description="按页编辑内容（分页文档使用）")
