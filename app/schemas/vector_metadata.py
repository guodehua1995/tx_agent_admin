"""
向量存储 Metadata 规范定义

所有入向量库的文档 metadata 必须符合此规范：
- BaseVectorMetadata: 所有文档共有的基础字段（必填）
- PagedDocumentMetadata: 分页文档（PPT 等）的扩展字段
- ContractMetadata: 合同文档的扩展字段（示例）

使用方式：
    from app.schemas.vector_metadata import BaseVectorMetadata, PagedDocumentMetadata

    # 普通文档
    meta = BaseVectorMetadata(title=..., source_type=..., knowledge_base_id=..., source_doc_id=..., doc_type_code=...)
    await rag_service.ingest_document(..., metadata=meta.to_dict())

    # 分页文档
    meta = PagedDocumentMetadata(title=..., ..., page_id=..., page_number=..., total_pages=...)
    llama_doc = LlamaDocument(text=..., metadata=meta.to_dict(), ...)
"""

from __future__ import annotations

from typing import Any, Optional

from pydantic import BaseModel, Field


class BaseVectorMetadata(BaseModel):
    """向量存储基础 Metadata（所有文档类型必须包含的字段）"""

    title: str = Field(..., description="文档标题")
    source_type: str = Field(..., description="来源类型: feishu_doc / upload / url")
    knowledge_base_id: str = Field(..., description="所属知识库ID")
    source_doc_id: str = Field(..., description="文档ID（对应 Document 表主键，LlamaIndex 会覆盖 doc_id/document_id/ref_doc_id，故用此字段）")
    doc_type_code: str = Field(..., description="文档类型编码: feishu_doc / ppt / contract 等")

    # ── 可选通用字段 ──
    file_type: Optional[str] = Field(None, description="文件类型: pdf / pptx / docx 等")
    is_context_expansion: bool = Field(False, description="是否为上下文扩展节点（运行时标记）")

    def to_dict(self) -> dict[str, Any]:
        """转为 dict，排除 None 值字段"""
        return {k: v for k, v in self.model_dump().items() if v is not None}


class PagedDocumentMetadata(BaseVectorMetadata):
    """分页文档 Metadata（PPT / 图片型PDF 等按页向量化的文档）"""

    page_id: int = Field(..., description="页面记录ID -> document_page.id")
    page_number: int = Field(..., description="页码（从1开始）")
    total_pages: int = Field(..., description="总页数")
    screenshot_url: Optional[str] = Field(None, description="页面截图URL")


class ContractMetadata(BaseVectorMetadata):
    """合同文档 Metadata"""

    # 合同级元信息（必填，由 LLM 在切片阶段提取）
    party_a: str = Field(..., description="甲方名称（简称）")
    party_b: str = Field(..., description="乙方名称（简称）")
    contract_type: str = Field(..., description="合同类型: 采购/服务/技术合作/框架协议/其他")

    # 条款级元信息
    clause_index: int = Field(..., description="条款序号，第0条为概要")
    clause_title: Optional[str] = Field(None, description="条款标题，如'违约责任'")
