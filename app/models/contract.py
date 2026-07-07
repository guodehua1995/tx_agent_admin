"""合同管理模块数据模型

ContractType: 合同类型字典表（支持动态扩展）
Contract: 合同主表，关联 Document 侧表
ContractClause: 合同条款表，单表父子结构
"""

from tortoise import fields

from .base import BaseModel, TimestampMixin


class ContractType(BaseModel, TimestampMixin):
    """合同类型字典表 — 支持 LLM 自动发现新类型并动态扩展"""

    name = fields.CharField(max_length=50, unique=True, description="类型名称(如：采购)")
    code = fields.CharField(max_length=50, unique=True, description="类型编码(如：purchase)")
    description = fields.TextField(null=True, description="类型说明")
    is_active = fields.BooleanField(default=True, description="是否启用", index=True)
    is_deleted = fields.BooleanField(default=False, description="是否已删除", db_index=True)

    class Meta:
        table = "contract_type"


class Contract(BaseModel, TimestampMixin):
    """合同主表 — 关联 Document 表 (1:1)

    document_id 为 null 时表示临时上传合同（无 Document 记录）。
    """

    document_id = fields.IntField(null=True, unique=True, description="关联 Document.id（临时合同为 null）")
    contract_type = fields.ForeignKeyField(
        "models.ContractType", null=True, description="合同类型ID -> contract_type.id", index=True,
    )
    party_a_client_id = fields.IntField(description="甲方 Client.id", index=True)
    party_b_client_id = fields.IntField(null=True, description="乙方 Client.id", index=True)
    project_name = fields.CharField(max_length=200, null=True, description="项目名称", index=True)
    signing_date = fields.DatetimeField(null=True, description="签订日期")
    effective_date = fields.DatetimeField(null=True, description="生效日期")
    expiry_date = fields.DatetimeField(null=True, description="到期日期", index=True)
    total_amount = fields.DecimalField(max_digits=14, decimal_places=2, null=True, description="合同金额")
    clause_count = fields.IntField(default=0, description="条款数量")
    summary = fields.TextField(null=True, description="合同摘要")
    document_url = fields.CharField(max_length=1000, null=True, description="合同文档链接（来自 Document.source_meta）")
    is_temporary = fields.BooleanField(default=False, index=True, description="是否为临时上传合同")
    is_deleted = fields.BooleanField(default=False, description="是否已删除", db_index=True)

    class Meta:
        table = "contract"


class ContractRiskReport(BaseModel, TimestampMixin):
    """合同风险审查报告表 — 独立存储，CASCADE 删除"""

    contract = fields.ForeignKeyField(
        "models.Contract", on_delete=fields.CASCADE,
        description="所属合同", index=True,
    )
    focus_areas = fields.JSONField(null=True, description="分析维度")
    status = fields.CharField(
        max_length=20, default="pending", index=True,
        description="审查状态: pending/analyzing/completed/failed",
    )
    report_content = fields.TextField(null=True, description="Markdown 审查报告")
    feishu_doc_url = fields.CharField(max_length=1000, null=True, description="飞书文档链接")
    risk_summary = fields.JSONField(null=True, description="风险汇总: {high:N, medium:N, low:N}")
    error_message = fields.TextField(null=True, description="失败原因")
    analyzed_at = fields.DatetimeField(null=True, description="分析完成时间")
    chat_id = fields.CharField(max_length=200, null=True, description="触发审查的飞书群聊ID")
    bot_id = fields.IntField(null=True, description="触发审查的飞书Bot ID")

    class Meta:
        table = "contract_risk_report"


class ContractClause(BaseModel, TimestampMixin):
    """合同条款表 — 单表父子结构"""

    contract = fields.ForeignKeyField(
        "models.Contract", related_name="clauses", description="所属合同", index=True,
    )
    parent = fields.ForeignKeyField(
        "models.ContractClause", null=True, related_name="children",
        description="父条款ID", index=True,
    )
    clause_index = fields.IntField(description="条款序号(0=概要)")
    clause_title = fields.CharField(max_length=200, null=True, description="条款标题")
    clause_level = fields.IntField(default=0, description="层级深度")
    original_text = fields.TextField(description="条款原文")
    summary = fields.TextField(null=True, description="条款摘要(用于向量检索)")
    sort_order = fields.IntField(default=0, description="排序号")
    summary_status = fields.CharField(
        max_length=20, default="summary_complete", index=True,
        description="摘要状态: pending_summary/summary_complete/pending_delete",
    )
    is_deleted = fields.BooleanField(default=False, description="是否已删除", db_index=True)

    class Meta:
        table = "contract_clause"
        unique_together = (("contract_id", "clause_index"),)