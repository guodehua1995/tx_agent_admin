"""合同模块 Pydantic 校验模型"""

from datetime import datetime
from decimal import Decimal
from typing import Optional

from pydantic import BaseModel, Field


# ── 合同类型 ──────────────────────────────────────────────────────


class ContractTypeCreate(BaseModel):
    name: str = Field(..., max_length=50, description="类型名称")
    code: str = Field(..., max_length=50, description="类型编码")
    description: Optional[str] = Field(None, description="类型说明")


class ContractTypeUpdate(BaseModel):
    name: Optional[str] = Field(None, max_length=50)
    description: Optional[str] = None
    is_active: Optional[bool] = None


# ── 合同条款 ──────────────────────────────────────────────────────


class ContractClauseCreate(BaseModel):
    contract_id: int = Field(..., description="所属合同ID")
    parent_id: Optional[int] = Field(None, description="父条款ID")
    clause_title: Optional[str] = Field(None, max_length=200, description="条款标题")
    original_text: str = Field(..., description="条款原文")


class ContractClauseUpdate(BaseModel):
    clause_title: Optional[str] = Field(None, max_length=200)
    original_text: Optional[str] = None
    summary: Optional[str] = None
    sort_order: Optional[int] = None


# ── 合同 ──────────────────────────────────────────────────────────


class ContractCreate(BaseModel):
    document_id: int = Field(..., description="关联 Document.id")
    contract_type_id: Optional[int] = Field(None, description="合同类型ID")
    party_a_client_id: int = Field(..., description="甲方 Client.id")
    party_b_client_id: Optional[int] = Field(None, description="乙方 Client.id")
    project_name: Optional[str] = Field(None, max_length=200, description="项目名称")
    signing_date: Optional[datetime] = Field(None, description="签订日期")
    effective_date: Optional[datetime] = Field(None, description="生效日期")
    expiry_date: Optional[datetime] = Field(None, description="到期日期")
    total_amount: Optional[Decimal] = Field(None, description="合同金额")
    summary: Optional[str] = Field(None, description="合同摘要")


class ContractUpdate(BaseModel):
    contract_type_id: Optional[int] = None
    party_a_client_id: Optional[int] = None
    party_b_client_id: Optional[int] = None
    project_name: Optional[str] = Field(None, max_length=200)
    signing_date: Optional[datetime] = None
    effective_date: Optional[datetime] = None
    expiry_date: Optional[datetime] = None
    total_amount: Optional[Decimal] = None
    summary: Optional[str] = None


# ── 合同搜索 ──────────────────────────────────────────────────────


class ContractSearchParams(BaseModel):
    keyword: Optional[str] = Field(None, description="关键词(标题/项目名)")
    party_a: Optional[str] = Field(None, description="甲方名称")
    party_b: Optional[str] = Field(None, description="乙方名称")
    contract_type_id: Optional[int] = Field(None, description="合同类型ID")
    start_date: Optional[datetime] = Field(None, description="签订日期起")
    end_date: Optional[datetime] = Field(None, description="签订日期止")
    page: int = Field(1, ge=1, description="页码")
    page_size: int = Field(20, ge=1, le=100, description="每页条数")


class ContractClauseSearchParams(BaseModel):
    contract_id: Optional[int] = Field(None, description="限定合同ID")
    keyword: Optional[str] = Field(None, description="条款内容关键词")
    clause_title: Optional[str] = Field(None, description="条款标题")
    page: int = Field(1, ge=1, description="页码")
    page_size: int = Field(20, ge=1, le=100, description="每页条数")


class ContractSummarySearchParams(BaseModel):
    keyword: Optional[str] = Field(None, description="摘要关键词")
    party_a: Optional[str] = Field(None, description="甲方名称")
    party_b: Optional[str] = Field(None, description="乙方名称")
    page: int = Field(1, ge=1, description="页码")
    page_size: int = Field(20, ge=1, le=100, description="每页条数")


# ── 合同对比 ──────────────────────────────────────────────────────


class ClauseCompareParams(BaseModel):
    """条款摘要对比"""
    clause_title: str = Field(..., description="条款标题关键词")
    contract_ids: Optional[list[int]] = Field(None, description="限定合同范围")
    party_a: Optional[str] = Field(None, description="限定甲方")
    party_b: Optional[str] = Field(None, description="限定乙方")


class ClauseFulltextCompareParams(BaseModel):
    """条款全文对比"""
    clause_title: str = Field(..., description="条款标题关键词")
    contract_ids: list[int] = Field(..., min_length=2, max_length=10, description="合同ID列表(2-10个)")


class SimilarContractParams(BaseModel):
    """查找相似合同"""
    contract_id: int = Field(..., description="参考合同ID")
    limit: int = Field(5, ge=1, le=20, description="返回数量")


# ── 合同生成 ──────────────────────────────────────────────────────


class ContractGenerateParams(BaseModel):
    contract_type: str = Field(..., description="目标合同类型")
    party_a: str = Field(..., description="甲方名称")
    party_b: Optional[str] = Field(None, description="乙方名称")
    requirements: Optional[str] = Field(None, description="需求描述")
    reference_contract_ids: Optional[list[int]] = Field(None, description="参考合同ID列表")


class ContractTypeMatchParams(BaseModel):
    """LLM 匹配/创建合同类型"""
    contract_name: str = Field(..., description="合同文件名/标题")
    snippet: Optional[str] = Field(None, description="合同内容片段(前500字)")