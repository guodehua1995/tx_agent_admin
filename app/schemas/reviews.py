from typing import Optional

from pydantic import BaseModel, Field


class ReviewSubmit(BaseModel):
    document_id: int = Field(..., description="文档ID")
    action: str = Field(..., description="审核动作: approve/reject")
    comment: Optional[str] = Field(None, description="审核意见")
