from decimal import Decimal
from typing import Optional

from pydantic import BaseModel, Field


# ── 甲方 ──────────────────────────────────────────────────────────


class ClientCreate(BaseModel):
    name: str = Field(..., max_length=200, description="甲方名称")
    short_name: Optional[str] = Field(None, max_length=100, description="甲方简称")
    contact: Optional[str] = Field(None, description="联系人")
    phone: Optional[str] = Field(None, description="联系电话")
    remark: Optional[str] = Field(None, description="备注")


class ClientUpdate(BaseModel):
    name: Optional[str] = Field(None, max_length=200)
    short_name: Optional[str] = Field(None, max_length=100)
    contact: Optional[str] = None
    phone: Optional[str] = None
    remark: Optional[str] = None
    is_active: Optional[bool] = None


# ── 报价明细 ─────────────────────────────────────────────────────


class QuotationItemCreate(BaseModel):
    parent_id: Optional[int] = Field(None, description="父级ID(null=一级)")
    name: str = Field(..., max_length=200, description="项目名称")
    code: Optional[str] = Field(None, max_length=100, description="项目编码")
    unit_price: Optional[Decimal] = Field(None, description="单价")
    unit: Optional[str] = Field(None, max_length=50, description="单位")
    remark: Optional[str] = None
    sort_order: int = Field(0, description="排序号")
    children: list["QuotationItemCreate"] = Field(default_factory=list, description="子级明细")


class QuotationItemUpdate(BaseModel):
    name: Optional[str] = Field(None, max_length=200)
    code: Optional[str] = None
    unit_price: Optional[Decimal] = None
    unit: Optional[str] = None
    remark: Optional[str] = None
    sort_order: Optional[int] = None


# ── 报价规则 ─────────────────────────────────────────────────────


class QuotationRuleCreate(BaseModel):
    client_id: int = Field(..., description="甲方ID")
    source_type: str = Field("manual", description="来源: manual/excel_import")
    items: list[QuotationItemCreate] = Field(default_factory=list, description="明细列表")
    remark: Optional[str] = None


class QuotationRuleSubmit(BaseModel):
    """提交审批"""
    rule_id: int = Field(..., description="规则ID")


class QuotationRuleEditDraft(BaseModel):
    """草稿原地编辑"""
    rule_id: int = Field(..., description="规则ID")
    items: list[QuotationItemCreate] = Field(default_factory=list, description="明细列表")


class QuotationRuleEditNewVersion(BaseModel):
    """从 active/expired 派生新版本"""
    source_rule_id: int = Field(..., description="源规则ID")
    items: list[QuotationItemCreate] = Field(default_factory=list, description="明细列表")
    source_type: str = Field("manual", description="来源: manual/excel_import")


class QuotationRuleIdOnly(BaseModel):
    """仅传 rule_id 的操作"""
    rule_id: int = Field(..., description="规则ID")


# ── 审批 ─────────────────────────────────────────────────────────


class ApprovalAction(BaseModel):
    rule_id: int = Field(..., description="规则ID")
    action: str = Field(..., description="approve/reject")
    comment: Optional[str] = Field(None, description="审批意见(驳回时必填)")


# ── Excel 导入 ────────────────────────────────────────────────────


class ExcelParseResult(BaseModel):
    """Excel 解析结果"""
    items: list[QuotationItemCreate] = Field(..., description="解析到的明细列表")
    warnings: list[str] = Field(default_factory=list, description="待确认项说明")
