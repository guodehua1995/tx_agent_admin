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

import json
from typing import Optional

from pydantic import BaseModel, Field

from app.log import logger
from app.services.contract_service import contract_service

from .base import BaseToolProvider, adapt_to_langchain, adapt_to_llamaindex


# ── LangChain 参数 Schema ────────────────────────────────────────


class ContractSearchArgs(BaseModel):
    keyword: str = Field(..., description="搜索关键词(合同名称/项目名)")
    party_a: Optional[str] = Field(None, description="甲方名称")
    party_b: Optional[str] = Field(None, description="乙方名称")
    contract_type: Optional[str] = Field(None, description="合同类型名称")
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


# ── 核心查询逻辑 ─────────────────────────────────────────────────


async def _contract_search(
    keyword: str,
    party_a: Optional[str] = None,
    party_b: Optional[str] = None,
    contract_type: Optional[str] = None,
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

        return json.dumps({
            "total": result["total"],
            "contracts": [
                {
                    "id": c["id"],
                    "project_name": c.get("project_name"),
                    "party_a": c.get("party_a_name"),
                    "party_b": c.get("party_b_name"),
                    "type": c.get("contract_type_name"),
                    "summary": c.get("summary", "")[:200] if c.get("summary") else "",
                    "signing_date": str(c.get("signing_date", ""))[:10] if c.get("signing_date") else None,
                    "expiry_date": str(c.get("expiry_date", ""))[:10] if c.get("expiry_date") else None,
                    "clause_count": c.get("clause_count"),
                }
                for c in items
            ],
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

        return json.dumps({
            "clause_title": clause_title,
            "count": len(result),
            "clauses": result[:limit],
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

        return json.dumps({
            "clause_title": clause_title,
            "count": len(result),
            "clauses": result,
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
                }
                for c in result
            ],
        }, ensure_ascii=False)
    except Exception as e:
        logger.error("[FindSimilarContractsTool] Error: %s", e, exc_info=True)
        return json.dumps({"error": f"查询异常: {str(e)}"}, ensure_ascii=False)


# ── 工具提供者 ────────────────────────────────────────────────────


class ContractSearchToolProvider(BaseToolProvider):
    TOOL_NAME = "contract_search"
    TOOL_DESC = (
        "结构化搜索合同。输入关键词(合同名称/项目名)、甲方名称、乙方名称、合同类型等条件，"
        "返回匹配的合同列表。当用户询问'XX公司的合同'、'XX项目的合同'、'XX类型的合同有哪些'时使用此工具。"
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