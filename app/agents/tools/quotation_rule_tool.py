"""
报价规则查询工具

Agent 通过自然语言提取甲方名称 → 查询最新生效规则 → 原样返回明细树。
支持精确匹配 + 模糊匹配候选，仅返回生效数据。
"""

from __future__ import annotations

import json
from typing import Optional

from pydantic import BaseModel, Field

from app.controllers.quotation import client_controller, quotation_item_controller, quotation_rule_controller
from app.log import logger

from .base import BaseToolProvider, adapt_to_langchain, adapt_to_llamaindex


# ── LangChain 参数 Schema ────────────────────────────────────────

class GetQuotationRuleArgs(BaseModel):
    """报价规则查询参数"""
    client_name: str = Field(..., description="甲方名称或关键词(必填)")
    item_keyword: Optional[str] = Field(None, description="项目关键词，用于过滤特定明细项")


# ── 核心查询逻辑 ─────────────────────────────────────────────────

async def _get_quotation_rule(
    client_name: str,
    item_keyword: Optional[str] = None,
) -> str:
    """查询甲方生效报价规则，返回 JSON 字符串"""
    try:
        # 1. 精确匹配甲方
        client = await client_controller.get_by_name(client_name)

        # 2. 未命中 → 模糊匹配返回候选
        if not client:
            candidates = await client_controller.search_by_keyword(client_name, limit=5)
            if not candidates:
                return json.dumps({"error": "未找到匹配的甲方，请确认名称"}, ensure_ascii=False)
            candidate_names = [c.name for c in candidates]
            return json.dumps({
                "hint": "未精确匹配到甲方，以下为候选列表，请用户确认：",
                "candidates": candidate_names,
            }, ensure_ascii=False)

        # 3. 查询生效规则
        rule = await quotation_rule_controller.get_active_rule(client.id)
        if not rule:
            return json.dumps({"error": f"甲方「{client.name}」暂无生效报价规则"}, ensure_ascii=False)

        # 4. 获取明细树
        items_tree = await quotation_item_controller.get_tree_by_rule(rule.id)

        # 5. 按 item_keyword 过滤（如果指定）
        if item_keyword:
            items_tree = _filter_items(items_tree, item_keyword)
            if not items_tree:
                return json.dumps({
                    "hint": f"甲方「{client.name}」的报价规则中未找到包含'{item_keyword}'的项目"
                }, ensure_ascii=False)

        result = {
            "client_name": client.name,
            "version": rule.version,
            "approved_at": rule.approved_at.strftime("%Y-%m-%d %H:%M") if rule.approved_at else None,
            "items": items_tree,
        }
        return json.dumps(result, ensure_ascii=False, default=str)

    except Exception as e:
        logger.error("[QuotationRuleTool] Error: %s", e, exc_info=True)
        return json.dumps({"error": f"查询异常: {str(e)}"}, ensure_ascii=False)


def _filter_items(items: list[dict], keyword: str) -> list[dict]:
    """过滤明细树：保留名称或编码包含关键词的项目"""
    filtered = []
    for item in items:
        children = item.get("children", [])
        matched_children = [
            c for c in children
            if keyword in (c.get("name") or "") or keyword in (c.get("code") or "")
        ]
        if keyword in (item.get("name") or "") or keyword in (item.get("code") or ""):
            filtered.append(item)
        elif matched_children:
            item_copy = {**item, "children": matched_children}
            filtered.append(item_copy)
    return filtered


# ── 工具提供者 ────────────────────────────────────────────────────

class QuotationRuleToolProvider(BaseToolProvider):
    """报价规则查询工具提供者"""

    TOOL_NAME = "get_quotation_rule"
    TOOL_DESC = (
        "查询甲方的最新生效报价规则。"
        "输入甲方名称或关键词(必填)，可选传入项目关键词以筛选特定明细。"
        "返回甲方报价规则的完整明细树（含名称、编码、单价、单位）。"
        "当用户询问'XX公司的报价'、'XX甲方价格'、'XX项目多少钱'等问题时使用此工具。"
    )

    async def build_llamaindex_tools(self, **kwargs) -> list:
        tool = adapt_to_llamaindex(_get_quotation_rule, self.TOOL_NAME, self.TOOL_DESC)
        return [tool]

    async def build_langchain_tools(self, **kwargs) -> list:
        tool = adapt_to_langchain(
            _get_quotation_rule, self.TOOL_NAME, self.TOOL_DESC, args_schema=GetQuotationRuleArgs
        )
        return [tool]


# 便捷实例
quotation_rule_tool_provider = QuotationRuleToolProvider()
