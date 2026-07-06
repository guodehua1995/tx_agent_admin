from tortoise import fields

from .base import BaseModel, TimestampMixin
from .enums import QuotationRuleStatus, RuleSourceType


class Client(BaseModel, TimestampMixin):
    """甲方/乙方 — 合同签约主体及报价规则归属主体"""
    name = fields.CharField(max_length=200, unique=True, description="名称")
    short_name = fields.CharField(max_length=100, null=True, description="简称", index=True)
    contact = fields.CharField(max_length=100, null=True, description="联系人")
    phone = fields.CharField(max_length=50, null=True, description="联系电话")
    social_credit_code = fields.CharField(max_length=50, null=True, description="统一社会信用代码", index=True)
    legal_representative = fields.CharField(max_length=100, null=True, description="法定代表人")
    registered_address = fields.CharField(max_length=500, null=True, description="注册地址")
    client_type = fields.CharField(max_length=20, null=True, description="主体类型: 企业/政府/个人", index=True)
    remark = fields.TextField(null=True, description="备注")
    is_active = fields.BooleanField(default=True, description="是否启用", index=True)
    is_deleted = fields.BooleanField(default=False, description="是否已删除", db_index=True)

    class Meta:
        table = "quotation_client"


class QuotationRule(BaseModel, TimestampMixin):
    """报价规则 — 归属某甲方的完整报价方案"""
    client_id = fields.IntField(description="甲方ID -> quotation_client.id", index=True)
    version = fields.IntField(default=1, description="版本号")
    status = fields.CharEnumField(
        QuotationRuleStatus, default=QuotationRuleStatus.DRAFT, description="状态"
    )
    source_type = fields.CharEnumField(
        RuleSourceType, default=RuleSourceType.MANUAL, description="来源类型"
    )
    creator_id = fields.IntField(description="创建人ID -> user.id", index=True)
    approver_id = fields.IntField(null=True, description="实际审批人ID -> user.id")
    approved_at = fields.DatetimeField(null=True, description="审批通过时间")
    reject_reason = fields.TextField(null=True, description="驳回原因")
    remark = fields.TextField(null=True, description="备注")
    is_deleted = fields.BooleanField(default=False, description="是否已删除", db_index=True)

    class Meta:
        table = "quotation_rule"
        unique_together = (("client_id", "version"),)


class QuotationItem(BaseModel, TimestampMixin):
    """报价明细 — 一级/二级层级结构"""
    rule_id = fields.IntField(description="报价规则ID -> quotation_rule.id", index=True)
    parent_id = fields.IntField(null=True, description="父级明细ID(null=一级项目)", index=True)
    name = fields.CharField(max_length=200, description="项目名称")
    code = fields.CharField(max_length=100, null=True, description="项目编码")
    unit_price = fields.DecimalField(max_digits=12, decimal_places=4, null=True, description="单价")
    unit = fields.CharField(max_length=50, null=True, description="单位(元/次、元/人天等)")
    remark = fields.TextField(null=True, description="备注")
    sort_order = fields.IntField(default=0, description="排序号")
    is_deleted = fields.BooleanField(default=False, description="是否已删除", db_index=True)

    class Meta:
        table = "quotation_item"


class VersionArchive(BaseModel, TimestampMixin):
    """版本归档 — 旧版本完整 JSON 快照，永久保留"""
    client_id = fields.IntField(description="甲方ID -> quotation_client.id", index=True)
    rule_id = fields.IntField(description="原规则ID -> quotation_rule.id", index=True)
    version = fields.IntField(description="归档版本号")
    snapshot = fields.JSONField(description="完整规则快照(含所有明细)")
    archived_reason = fields.CharField(max_length=100, description="归档原因: new_version/reimport")
    archived_by = fields.IntField(description="触发归档的用户ID", index=True)

    class Meta:
        table = "quotation_version_archive"
