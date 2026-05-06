from typing import Optional

from pydantic import BaseModel, Field


class DocTemplateCreate(BaseModel):
    name: str = Field(..., description="模板名称")
    markdown_content: str = Field(..., description="Markdown模板内容")
    folder_token: str = Field(..., description="飞书文件夹Token")
    description: str = Field(..., description="模板描述(告知AI使用场景)")
    naming_format: Optional[str] = Field(None, description="命名格式")


class DocTemplateUpdate(BaseModel):
    id: int
    name: Optional[str] = None
    markdown_content: Optional[str] = None
    folder_token: Optional[str] = None
    description: Optional[str] = None
    naming_format: Optional[str] = None


class ParseUrlRequest(BaseModel):
    url: str = Field(..., description="飞书云文档URL")


class GenerateDocRequest(BaseModel):
    template_id: int = Field(..., description="模板ID")
    markdown_content: str = Field(..., description="生成的Markdown内容")
    doc_name: str = Field(..., description="文档名称")
