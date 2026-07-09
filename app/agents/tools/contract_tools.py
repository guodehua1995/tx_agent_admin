"""合同管理 Agent 工具集

提供飞书 Bot / Web 对话中可调用的合同管理能力：
- contract_search: 结构化搜索合同
- contract_stats: 合同统计
- contract_clause_search: 条款搜索
- contract_summary_search: 合同摘要搜索
- compare_clause_summaries: 条款摘要对比
- compare_clause_fulltext: 条款全文对比
- find_similar_contracts: 查找相似合同
"""

from __future__ import annotations

import contextvars
import json
from typing import Optional

from pydantic import BaseModel, Field
from tortoise.expressions import Q

from app.log import logger
from app.services.contract_service import contract_service
from app.models.contract import Contract, ContractClause, ContractRiskReport

# 飞书上下文变量（由 feishu_ws_manager / feishu.py 在消息处理入口设置）
chat_context: contextvars.ContextVar = contextvars.ContextVar("chat_context", default=None)

from .base import BaseToolProvider, adapt_to_langchain, adapt_to_llamaindex


# ── LangChain 参数 Schema ────────────────────────────────────────


class ContractSearchArgs(BaseModel):
    keyword: str = Field(..., description="搜索关键词(合同名称/项目名)")
    party_a: Optional[str] = Field(None, description="甲方名称")
    party_b: Optional[str] = Field(None, description="乙方名称")
    contract_type: Optional[str] = Field(None, description="合同类型名称")
    include_summary: bool = Field(False, description="是否返回合同完整摘要(500字)，默认False仅返回简要信息")
    limit: int = Field(10, description="返回条数上限")


class ContractStatsArgs(BaseModel):
    """无需参数"""
    pass


class ContractClauseSearchArgs(BaseModel):
    keyword: str = Field(..., description="条款内容关键词")
    clause_title: Optional[str] = Field(None, description="条款标题关键词")
    contract_id: Optional[int] = Field(None, description="限定合同ID")
    limit: int = Field(10, description="返回条数上限")


class ContractSummarySearchArgs(BaseModel):
    keyword: Optional[str] = Field(None, description="摘要关键词")
    party_a: Optional[str] = Field(None, description="甲方名称")
    limit: int = Field(10, description="返回条数上限")


class ClauseCompareArgs(BaseModel):
    clause_title: str = Field(..., description="条款标题关键词(如: 违约责任)")
    contract_ids: Optional[list[int]] = Field(None, description="限定合同ID列表")
    party_a: Optional[str] = Field(None, description="限定甲方")
    limit: int = Field(20, description="返回条数上限")


class ClauseFulltextCompareArgs(BaseModel):
    clause_title: str = Field(..., description="条款标题关键词")
    contract_ids: list[int] = Field(..., description="合同ID列表(2-10个)")


class SimilarContractArgs(BaseModel):
    contract_id: int = Field(..., description="参考合同ID")
    limit: int = Field(5, description="返回数量")


class ContractClauseQueryArgs(BaseModel):
    contract_id: int = Field(..., description="合同ID")
    keyword: str = Field(
        ...,
        description="条款关键词，模糊搜索条款标题和原文。多个关键词用逗号分隔，如'违约责任,争议解决'"
    )


class ContractReviewTriggerArgs(BaseModel):
    contract_id: int = Field(..., description="合同ID")
    focus_areas: Optional[str] = Field(None, description="分析维度，如'法律合规,商业风险'")


# ── 核心查询逻辑 ─────────────────────────────────────────────────


async def _batch_fetch_contract_urls(contract_ids: set[int]) -> dict[int, str | None]:
    """批量获取合同文档链接，避免 N+1 查询"""
    if not contract_ids:
        return {}
    contracts = await Contract.filter(id__in=list(contract_ids), is_deleted=False).all()
    return {c.id: c.document_url for c in contracts}


async def _contract_search(
    keyword: str,
    party_a: Optional[str] = None,
    party_b: Optional[str] = None,
    contract_type: Optional[str] = None,
    include_summary: bool = False,
    limit: int = 10,
) -> str:
    """结构化搜索合同"""
    try:
        result = await contract_service.search_contracts({
            "keyword": keyword,
            "party_a": party_a,
            "party_b": party_b,
            "page": 1,
            "page_size": limit,
        })
        items = result["items"]
        if not items:
            return json.dumps({"message": "未找到匹配的合同"}, ensure_ascii=False)

        contracts = []
        for c in items:
            item = {
                "id": c["id"],
                "project_name": c.get("project_name"),
                "party_a": c.get("party_a_name"),
                "party_b": c.get("party_b_name"),
                "type": c.get("contract_type_name"),
                "signing_date": str(c.get("signing_date", ""))[:10] if c.get("signing_date") else None,
                "expiry_date": str(c.get("expiry_date", ""))[:10] if c.get("expiry_date") else None,
                "clause_count": c.get("clause_count"),
                "url": c.get("document_url"),
            }
            if include_summary:
                item["summary"] = c.get("summary", "")[:500] if c.get("summary") else ""
            else:
                item["summary"] = c.get("summary", "")[:200] if c.get("summary") else ""
            contracts.append(item)

        return json.dumps({
            "total": result["total"],
            "contracts": contracts,
        }, ensure_ascii=False)
    except Exception as e:
        logger.error("[ContractSearchTool] Error: %s", e, exc_info=True)
        return json.dumps({"error": f"查询异常: {str(e)}"}, ensure_ascii=False)


async def _contract_stats() -> str:
    """获取合同统计信息"""
    try:
        stats = await contract_service.get_contract_stats_sql()
        return json.dumps(stats, ensure_ascii=False)
    except Exception as e:
        logger.error("[ContractStatsTool] Error: %s", e, exc_info=True)
        return json.dumps({"error": f"统计异常: {str(e)}"}, ensure_ascii=False)


async def _contract_clause_search(
    keyword: str,
    clause_title: Optional[str] = None,
    contract_id: Optional[int] = None,
    limit: int = 10,
) -> str:
    """搜索合同条款"""
    try:
        result = await contract_service.search_clauses({
            "keyword": keyword,
            "clause_title": clause_title,
            "contract_id": contract_id,
            "page": 1,
            "page_size": limit,
        })
        items = result["items"]
        if not items:
            return json.dumps({"message": "未找到匹配的条款"}, ensure_ascii=False)

        # 批量获取合同链接
        contract_ids = {c.get("contract_id") for c in items if c.get("contract_id")}
        contract_urls = await _batch_fetch_contract_urls(contract_ids)

        return json.dumps({
            "total": result["total"],
            "clauses": [
                {
                    "id": c["id"],
                    "contract_id": c["contract_id"],
                    "clause_title": c.get("clause_title"),
                    "clause_index": c.get("clause_index"),
                    "original_text": c.get("original_text", "")[:300],
                    "summary": c.get("summary", "")[:200] if c.get("summary") else "",
                    "document_url": contract_urls.get(c["contract_id"]),
                }
                for c in items
            ],
        }, ensure_ascii=False)
    except Exception as e:
        logger.error("[ContractClauseSearchTool] Error: %s", e, exc_info=True)
        return json.dumps({"error": f"查询异常: {str(e)}"}, ensure_ascii=False)


async def _contract_summary_search(
    keyword: Optional[str] = None,
    party_a: Optional[str] = None,
    limit: int = 10,
) -> str:
    """搜索合同摘要"""
    try:
        result = await contract_service.search_contract_summaries({
            "keyword": keyword,
            "party_a": party_a,
            "page": 1,
            "page_size": limit,
        })
        items = result["items"]
        if not items:
            return json.dumps({"message": "未找到匹配的合同摘要"}, ensure_ascii=False)

        return json.dumps({
            "total": result["total"],
            "summaries": [
                {
                    "id": c["id"],
                    "project_name": c.get("project_name"),
                    "summary": c.get("summary", "")[:500],
                    "url": c.get("document_url"),
                }
                for c in items
            ],
        }, ensure_ascii=False)
    except Exception as e:
        logger.error("[ContractSummarySearchTool] Error: %s", e, exc_info=True)
        return json.dumps({"error": f"查询异常: {str(e)}"}, ensure_ascii=False)


async def _compare_clause_summaries(
    clause_title: str,
    contract_ids: Optional[list[int]] = None,
    party_a: Optional[str] = None,
    limit: int = 20,
) -> str:
    """对比同类条款摘要"""
    try:
        result = await contract_service.compare_clause_summaries(
            clause_title=clause_title,
            contract_ids=contract_ids,
            party_a=party_a,
        )
        if not result:
            return json.dumps({"message": "未找到匹配的条款"}, ensure_ascii=False)

        # 批量获取合同链接
        contract_ids = {c.get("contract_id") for c in result if c.get("contract_id")}
        contract_urls = await _batch_fetch_contract_urls(contract_ids)

        clauses = []
        for c in result[:limit]:
            clauses.append({
                **c,
                "document_url": contract_urls.get(c["contract_id"]),
            })

        return json.dumps({
            "clause_title": clause_title,
            "count": len(result),
            "clauses": clauses,
        }, ensure_ascii=False)
    except Exception as e:
        logger.error("[CompareClauseSummariesTool] Error: %s", e, exc_info=True)
        return json.dumps({"error": f"对比异常: {str(e)}"}, ensure_ascii=False)


async def _compare_clause_fulltext(
    clause_title: str,
    contract_ids: list[int],
) -> str:
    """对比同类条款全文"""
    try:
        result = await contract_service.compare_clause_fulltext(
            clause_title=clause_title,
            contract_ids=contract_ids,
        )
        if not result:
            return json.dumps({"message": "未找到匹配的条款"}, ensure_ascii=False)

        # 批量获取合同链接
        contract_ids = {c.get("contract_id") for c in result if c.get("contract_id")}
        contract_urls = await _batch_fetch_contract_urls(contract_ids)

        clauses = []
        for c in result:
            clauses.append({
                **c,
                "document_url": contract_urls.get(c["contract_id"]),
            })

        return json.dumps({
            "clause_title": clause_title,
            "count": len(result),
            "clauses": clauses,
        }, ensure_ascii=False)
    except Exception as e:
        logger.error("[CompareClauseFulltextTool] Error: %s", e, exc_info=True)
        return json.dumps({"error": f"对比异常: {str(e)}"}, ensure_ascii=False)


async def _find_similar_contracts(
    contract_id: int,
    limit: int = 5,
) -> str:
    """查找相似合同"""
    try:
        result = await contract_service.find_similar_contracts(
            contract_id=contract_id, limit=limit,
        )
        if not result:
            return json.dumps({"message": "未找到相似合同"}, ensure_ascii=False)

        return json.dumps({
            "reference_contract_id": contract_id,
            "similar": [
                {
                    "id": c["id"],
                    "project_name": c.get("project_name"),
                    "type": c.get("contract_type_name"),
                    "party_a": c.get("party_a_name"),
                    "party_b": c.get("party_b_name"),
                    "url": c.get("document_url"),
                }
                for c in result
            ],
        }, ensure_ascii=False)
    except Exception as e:
        logger.error("[FindSimilarContractsTool] Error: %s", e, exc_info=True)
        return json.dumps({"error": f"查询异常: {str(e)}"}, ensure_ascii=False)


async def _query_contract_clause(
    contract_id: int,
    keyword: str,
) -> str:
    """在指定合同内模糊搜索条款，返回匹配条款及其子条款原文

    多个关键词用逗号分隔，每个关键词最多返回2条结果。
    """
    try:
        logger.debug(f"[_query_contract_clause] contract_id={contract_id}, keyword={keyword}")

        # 按逗号（中英文）拆分关键词
        keywords = [kw.strip() for kw in keyword.replace("，", ",").split(",") if kw.strip()]

        seen_ids = set()
        all_results = []

        for kw in keywords:
            clauses = await ContractClause.filter(
                contract_id=contract_id,
                is_deleted=False,
            ).filter(
                Q(clause_title__icontains=kw) | Q(original_text__icontains=kw),
            ).order_by("clause_index").limit(10)

            if not clauses:
                continue

            kw_results = []
            for clause in clauses:
                if clause.id in seen_ids:
                    continue
                seen_ids.add(clause.id)

                children = await ContractClause.filter(
                    contract_id=contract_id,
                    parent_id=clause.id,
                    is_deleted=False,
                ).order_by("clause_index")

                child_texts = [
                    f"{c.clause_title or ''}: {c.original_text[:300]}"
                    for c in children
                ]

                kw_results.append({
                    "clause_index": clause.clause_index,
                    "clause_title": clause.clause_title,
                    "clause_level": clause.clause_level,
                    "original_text": clause.original_text[:500],
                    "children": child_texts if child_texts else None,
                })

                # 每个关键词只保留前2条
                if len(kw_results) >= 2:
                    break

            all_results.extend(kw_results)

        if not all_results:
            logger.debug(f"[_query_contract_clause] No clauses found for keywords={keywords}")
            return json.dumps({"message": f"未找到匹配条款"}, ensure_ascii=False)

        # 获取合同链接
        contract = await Contract.filter(id=contract_id, is_deleted=False).first()
        document_url = contract.document_url if contract else None

        logger.debug(f"[_query_contract_clause] Found {len(all_results)} matching clauses")
        return json.dumps({
            "contract_id": contract_id,
            "document_url": document_url,
            "count": len(all_results),
            "clauses": all_results,
        }, ensure_ascii=False)
    except Exception as e:
        logger.error(f"[_query_contract_clause] Error: {e}", exc_info=True)
        return json.dumps({"error": f"查询异常: {str(e)}"}, ensure_ascii=False)


# [保留] 审核 Agent 专用：创建审查记录并触发异步审查
# 已从合同 Agent 工具列表中移除（审核触发已拆分到独立审核 Agent）。
# 后续如需在对话中重新挂载审核触发能力，可加回 build_chat_tools() 的 contract_providers。
async def _trigger_contract_review(
    contract_id: int,
    focus_areas: Optional[str] = None,
) -> str:
    """创建合同审查记录，触发异步审查"""
    try:
        logger.debug(f"[_trigger_contract_review] contract_id={contract_id}, focus_areas={focus_areas}")

        # 检查是否已有审查记录
        existing = await ContractRiskReport.filter(
            contract_id=contract_id,
            status__in=["pending", "analyzing"],
        ).first()
        if existing:
            logger.debug(f"[_trigger_contract_review] Already reviewing: status={existing.status}")
            contract = await Contract.filter(id=contract_id, is_deleted=False).first()
            return json.dumps({
                "message": "该合同正在审查中，请稍后再试",
                "status": existing.status,
                "contract_id": contract_id,
                "document_url": contract.document_url if contract else None,
            }, ensure_ascii=False)

        # 检查是否有已完成报告
        completed = await ContractRiskReport.filter(
            contract_id=contract_id,
            status="completed",
        ).order_by("-created_at").first()
        if completed and completed.feishu_doc_url:
            logger.debug(f"[_trigger_contract_review] Already completed: report_id={completed.id}")
            contract = await Contract.filter(id=contract_id, is_deleted=False).first()
            return json.dumps({
                "message": "该合同已有审查报告",
                "report_id": completed.id,
                "feishu_doc_url": completed.feishu_doc_url,
                "contract_id": contract_id,
                "document_url": contract.document_url if contract else None,
                "analyzed_at": completed.analyzed_at.isoformat() if completed.analyzed_at else None,
            }, ensure_ascii=False)

        # 从上下文中获取 chat_id 和 bot_id
        ctx = chat_context.get(None)
        chat_id = ctx.get("chat_id") if ctx else None
        bot_id = ctx.get("bot_id") if ctx else None

        logger.debug(f"[_trigger_contract_review] chat_id={chat_id}, bot_id={bot_id}")

        # 解析 focus_areas
        areas = None
        if focus_areas:
            areas = [a.strip() for a in focus_areas.split(",") if a.strip()]

        # 创建审查记录
        report = await ContractRiskReport.create(
            contract_id=contract_id,
            focus_areas=areas,
            status="pending",
            chat_id=chat_id,
            bot_id=bot_id,
        )

        logger.debug(f"[_trigger_contract_review] Created review record: report_id={report.id}")

        # 获取合同链接
        contract = await Contract.filter(id=contract_id, is_deleted=False).first()
        document_url = contract.document_url if contract else None

        return json.dumps({
            "message": "已加入审查队列，完成后会通知您",
            "report_id": report.id,
            "contract_id": contract_id,
            "document_url": document_url,
        }, ensure_ascii=False)
    except Exception as e:
        logger.error(f"[_trigger_contract_review] Error: {e}", exc_info=True)
        return json.dumps({"error": f"创建审查任务失败: {str(e)}"}, ensure_ascii=False)


# ── 工具提供者 ────────────────────────────────────────────────────


class ContractSearchToolProvider(BaseToolProvider):
    TOOL_NAME = "contract_search"
    TOOL_DESC = (
        "结构化搜索合同。输入关键词(合同名称/项目名)、甲方名称、乙方名称、合同类型等条件，"
        "返回匹配的合同列表。当用户询问'XX公司的合同'、'XX项目的合同'、'XX类型的合同有哪些'时使用此工具。"
        "设置 include_summary=True 可返回合同完整摘要(500字)，适合用户询问'XX合同主要约定什么'等场景。"
    )

    async def build_llamaindex_tools(self, **kwargs) -> list:
        return [adapt_to_llamaindex(_contract_search, self.TOOL_NAME, self.TOOL_DESC)]

    async def build_langchain_tools(self, **kwargs) -> list:
        return [adapt_to_langchain(_contract_search, self.TOOL_NAME, self.TOOL_DESC, args_schema=ContractSearchArgs)]


class ContractStatsToolProvider(BaseToolProvider):
    TOOL_NAME = "contract_stats"
    TOOL_DESC = (
        "获取合同统计数据。返回合同总数、按类型分布、按甲方分布、即将到期合同数。"
        "当用户询问'合同统计'、'有多少合同'、'合同分布情况'时使用此工具。"
    )

    async def build_llamaindex_tools(self, **kwargs) -> list:
        return [adapt_to_llamaindex(_contract_stats, self.TOOL_NAME, self.TOOL_DESC)]

    async def build_langchain_tools(self, **kwargs) -> list:
        return [adapt_to_langchain(_contract_stats, self.TOOL_NAME, self.TOOL_DESC, args_schema=ContractStatsArgs)]


class ContractClauseSearchToolProvider(BaseToolProvider):
    TOOL_NAME = "contract_clause_search"
    TOOL_DESC = (
        "搜索合同条款内容。输入关键词、可选条款标题或限定合同ID，"
        "返回匹配的条款列表。当用户询问'XX条款怎么写的'、'哪些合同包含XX条款'时使用此工具。"
    )

    async def build_llamaindex_tools(self, **kwargs) -> list:
        return [adapt_to_llamaindex(_contract_clause_search, self.TOOL_NAME, self.TOOL_DESC)]

    async def build_langchain_tools(self, **kwargs) -> list:
        return [adapt_to_langchain(
            _contract_clause_search, self.TOOL_NAME, self.TOOL_DESC, args_schema=ContractClauseSearchArgs,
        )]


class ContractSummarySearchToolProvider(BaseToolProvider):
    TOOL_NAME = "contract_summary_search"
    TOOL_DESC = (
        "搜索合同摘要。输入关键词或甲方名称，返回匹配的合同摘要列表。"
        "当用户询问'XX合同主要约定什么'、'XX甲方的合同概况'时使用此工具。"
    )

    async def build_llamaindex_tools(self, **kwargs) -> list:
        return [adapt_to_llamaindex(_contract_summary_search, self.TOOL_NAME, self.TOOL_DESC)]

    async def build_langchain_tools(self, **kwargs) -> list:
        return [adapt_to_langchain(
            _contract_summary_search, self.TOOL_NAME, self.TOOL_DESC, args_schema=ContractSummarySearchArgs,
        )]


class CompareClauseSummariesToolProvider(BaseToolProvider):
    TOOL_NAME = "compare_clause_summaries"
    TOOL_DESC = (
        "对比同类条款的摘要。输入条款标题关键词(如: 违约责任、保密条款)，可选限定合同范围和甲方，"
        "返回各合同中同类条款的摘要列表。当用户询问'XX条款在不同合同中有什么不同'时使用此工具。"
    )

    async def build_llamaindex_tools(self, **kwargs) -> list:
        return [adapt_to_llamaindex(_compare_clause_summaries, self.TOOL_NAME, self.TOOL_DESC)]

    async def build_langchain_tools(self, **kwargs) -> list:
        return [adapt_to_langchain(
            _compare_clause_summaries, self.TOOL_NAME, self.TOOL_DESC, args_schema=ClauseCompareArgs,
        )]


class CompareClauseFulltextToolProvider(BaseToolProvider):
    TOOL_NAME = "compare_clause_fulltext"
    TOOL_DESC = (
        "对比同类条款的完整原文。输入条款标题关键词和需要对比的合同ID列表(2-10个)，"
        "返回各合同中同类条款的完整原文。当用户需要深入对比具体条款措辞时使用此工具。"
    )

    async def build_llamaindex_tools(self, **kwargs) -> list:
        return [adapt_to_llamaindex(_compare_clause_fulltext, self.TOOL_NAME, self.TOOL_DESC)]

    async def build_langchain_tools(self, **kwargs) -> list:
        return [adapt_to_langchain(
            _compare_clause_fulltext, self.TOOL_NAME, self.TOOL_DESC, args_schema=ClauseFulltextCompareArgs,
        )]


class FindSimilarContractsToolProvider(BaseToolProvider):
    TOOL_NAME = "find_similar_contracts"
    TOOL_DESC = (
        "查找与指定合同相似的合同。输入合同ID，返回基于合同类型和签约主体的相似合同列表。"
        "当用户询问'和XX合同类似的合同有哪些'时使用此工具。"
    )

    async def build_llamaindex_tools(self, **kwargs) -> list:
        return [adapt_to_llamaindex(_find_similar_contracts, self.TOOL_NAME, self.TOOL_DESC)]

    async def build_langchain_tools(self, **kwargs) -> list:
        return [adapt_to_langchain(
            _find_similar_contracts, self.TOOL_NAME, self.TOOL_DESC, args_schema=SimilarContractArgs,
        )]


class ContractClauseQueryToolProvider(BaseToolProvider):
    """审查 Agent 专用：在指定合同内模糊搜索条款"""
    TOOL_NAME = "query_contract_clause"
    TOOL_DESC = (
        "在指定合同内模糊搜索条款。输入合同ID和关键词，"
        "返回匹配条款（含标题和原文）及其子条款原文。"
        "当审查某条款时，如果发现该条款引用了其他条款（如'按第七条执行'），"
        "必须调用此工具查询被引用条款的原文，确保交叉验证后再给出审查意见。"
        "查询不到时返回空列表，此时应在报告中标注引用缺失。"
        "多个关键词必须用逗号','分隔，每个关键词最多返回2条结果。"
    )

    async def build_llamaindex_tools(self, **kwargs) -> list:
        return [adapt_to_llamaindex(_query_contract_clause, self.TOOL_NAME, self.TOOL_DESC)]

    async def build_langchain_tools(self, **kwargs) -> list:
        return [adapt_to_langchain(
            _query_contract_clause, self.TOOL_NAME, self.TOOL_DESC,
            args_schema=ContractClauseQueryArgs,
        )]


# [保留] 审核 Agent 专用工具提供者
# 已从合同 Agent 工具列表中移除（审核触发已拆分到独立审核 Agent）。
# 后续如需重新挂载，可加回 build_chat_tools() 的 contract_providers。
class ContractReviewTriggerToolProvider(BaseToolProvider):
    """聊天触发合同审查"""
    TOOL_NAME = "trigger_contract_review"
    TOOL_DESC = (
        "触发合同风险审查。输入合同ID和可选的分析维度（如'法律合规,商业风险'），"
        "创建审查任务并加入队列，完成后会通过飞书通知用户。"
        "当用户要求'审查合同'、'分析合同风险'、'检查合同漏洞'时使用此工具。"
    )

    async def build_llamaindex_tools(self, **kwargs) -> list:
        return [adapt_to_llamaindex(_trigger_contract_review, self.TOOL_NAME, self.TOOL_DESC)]

    async def build_langchain_tools(self, **kwargs) -> list:
        return [adapt_to_langchain(
            _trigger_contract_review, self.TOOL_NAME, self.TOOL_DESC,
            args_schema=ContractReviewTriggerArgs,
        )]