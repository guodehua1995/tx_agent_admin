import json
import logging
from datetime import datetime

from app.controllers.quotation import (
    client_controller,
    quotation_item_controller,
    quotation_rule_controller,
)
from app.models.enums import QuotationRuleStatus
from app.models.global_config import GlobalConfig
from app.models.quotation import QuotationItem, QuotationRule, VersionArchive

logger = logging.getLogger(__name__)


class QuotationService:

    async def create_rule(
        self, client_id: int, creator_id: int, items: list[dict], source_type: str = "manual"
    ) -> QuotationRule:
        """新建报价规则（草稿状态）"""
        version = await quotation_rule_controller.get_next_version(client_id)
        rule = await QuotationRule.create(
            client_id=client_id,
            version=version,
            status=QuotationRuleStatus.DRAFT,
            source_type=source_type,
            creator_id=creator_id,
        )
        await self._batch_create_items(rule.id, items)
        logger.info("[Quotation] Created rule: id=%s, client=%s, v=%s", rule.id, client_id, version)
        return rule

    async def submit_for_approval(self, rule_id: int, submitter_id: int) -> QuotationRule:
        """提交审批（状态 DRAFT → PENDING_APPROVAL）"""
        rule = await quotation_rule_controller.get(id=rule_id)
        if rule.status != QuotationRuleStatus.DRAFT:
            raise ValueError("仅草稿状态可提交审批")

        rule.status = QuotationRuleStatus.PENDING_APPROVAL
        rule.reject_reason = None  # 清空上次驳回原因
        await rule.save()
        return rule

    async def check_approver(self, user_id: int) -> bool:
        """检查用户是否为配置的审批人"""
        config = await GlobalConfig.filter(config_key="quotation_approver_ids").first()
        if not config:
            return False
        value = config.config_value
        approver_ids = json.loads(value) if isinstance(value, str) else value
        return user_id in approver_ids

    async def approve(self, rule_id: int, approver_id: int):
        """审批通过 → 旧版本 archived + 快照 → 新版本生效"""
        rule = await quotation_rule_controller.get(id=rule_id)
        if rule.status != QuotationRuleStatus.PENDING_APPROVAL:
            raise ValueError("该规则不在待审批状态")

        # 1. 旧 active 版本 → archived + 快照
        old_active = await quotation_rule_controller.get_active_rule(rule.client_id)
        if old_active:
            await self._archive_rule(old_active, archived_by=approver_id, reason="new_version")

        # 2. 新版本生效
        rule.status = QuotationRuleStatus.ACTIVE
        rule.approver_id = approver_id
        rule.approved_at = datetime.now()
        await rule.save()

        logger.info("[Quotation] Approved: rule_id=%s, client_id=%s", rule_id, rule.client_id)

    async def reject(self, rule_id: int, approver_id: int, reason: str):
        """审批驳回 → 退回草稿，记录驳回原因"""
        rule = await quotation_rule_controller.get(id=rule_id)
        if rule.status != QuotationRuleStatus.PENDING_APPROVAL:
            raise ValueError("该规则不在待审批状态")

        rule.status = QuotationRuleStatus.DRAFT
        rule.reject_reason = reason
        await rule.save()

    async def edit_draft(self, rule_id: int, items: list[dict]) -> QuotationRule:
        """草稿原地编辑：软删旧明细 → 重建明细"""
        rule = await quotation_rule_controller.get(id=rule_id)
        if rule.status != QuotationRuleStatus.DRAFT:
            raise ValueError("仅草稿状态可编辑")

        # 软删旧明细
        await QuotationItem.filter(rule_id=rule.id, is_deleted=False).update(is_deleted=True)
        # 重建明细
        await self._batch_create_items(rule.id, items)
        logger.info("[Quotation] Edited draft: rule_id=%s", rule_id)
        return rule

    async def edit_as_new_version(
        self, source_rule_id: int, items: list[dict], user_id: int, source_type: str = "manual"
    ) -> QuotationRule:
        """从 active/expired 派生新版本：version+1, 状态直接 pending_approval"""
        source = await quotation_rule_controller.get(id=source_rule_id)
        if source.status not in (QuotationRuleStatus.ACTIVE, QuotationRuleStatus.EXPIRED):
            raise ValueError("仅生效中或已失效版本可派生新版本")

        # 并发约束：同一甲方不能同时有 pending_approval
        existing_pending = await QuotationRule.filter(
            client_id=source.client_id, status=QuotationRuleStatus.PENDING_APPROVAL, is_deleted=False
        ).first()
        if existing_pending:
            raise ValueError("该甲方已有待审批的规则，不可重复提交")

        new_version = source.version + 1
        new_rule = await QuotationRule.create(
            client_id=source.client_id,
            version=new_version,
            status=QuotationRuleStatus.PENDING_APPROVAL,
            source_type=source_type,
            creator_id=user_id,
        )
        await self._batch_create_items(new_rule.id, items)
        logger.info(
            "[Quotation] New version from source: source=%s, new=%s, v=%s",
            source_rule_id, new_rule.id, new_version,
        )
        return new_rule

    async def cancel_rule(self, rule_id: int, user_id: int) -> QuotationRule:
        """取消生效版本：状态直接变 expired（无快照，仍可在规则列表派生新版本）"""
        rule = await quotation_rule_controller.get(id=rule_id)
        if rule.status != QuotationRuleStatus.ACTIVE:
            raise ValueError("仅生效中的规则可取消")

        rule.status = QuotationRuleStatus.EXPIRED
        await rule.save()
        logger.info("[Quotation] Cancelled: rule_id=%s", rule_id)
        return rule

    async def delete_draft(self, rule_id: int):
        """删除草稿：软删 rule + items"""
        rule = await quotation_rule_controller.get(id=rule_id)
        if rule.status != QuotationRuleStatus.DRAFT:
            raise ValueError("仅草稿状态可删除")

        await QuotationItem.filter(rule_id=rule.id, is_deleted=False).update(is_deleted=True)
        rule.is_deleted = True
        await rule.save()
        logger.info("[Quotation] Deleted draft: rule_id=%s", rule_id)

    async def _archive_rule(self, rule: QuotationRule, archived_by: int, reason: str):
        """创建完整快照 + 状态变 archived（仅用于审批通过时归档旧版本）"""
        items = await QuotationItem.filter(rule_id=rule.id, is_deleted=False).order_by("sort_order")
        snapshot = {
            "rule": await rule.to_dict(),
            "items": [await item.to_dict() for item in items],
        }
        await VersionArchive.create(
            client_id=rule.client_id,
            rule_id=rule.id,
            version=rule.version,
            snapshot=snapshot,
            archived_reason=reason,
            archived_by=archived_by,
        )
        rule.status = QuotationRuleStatus.ARCHIVED
        await rule.save()

    async def _batch_create_items(self, rule_id: int, items: list[dict]):
        """批量创建明细（处理一级/二级层级）"""
        allowed_fields = {"name", "code", "unit_price", "unit", "remark", "sort_order"}
        for item_data in items:
            children = item_data.pop("children", [])
            parent_data = {k: v for k, v in item_data.items() if k in allowed_fields}
            parent = await QuotationItem.create(rule_id=rule_id, **parent_data)
            for child_data in children:
                child_clean = {k: v for k, v in child_data.items() if k in allowed_fields}
                await QuotationItem.create(rule_id=rule_id, parent_id=parent.id, **child_clean)


quotation_service = QuotationService()
