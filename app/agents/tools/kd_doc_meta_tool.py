"""
知识库文档元信息查询工具

以知识库为维度，提供文档数量统计、文档列表、按条件筛选等元信息查询能力。
仅基于 Document 表的结构化字段（标题、文档类型、状态、创建/修改时间），
不涉及 JSON 字段或向量库查询。

同时输出 LlamaIndex FunctionTool 和 LangChain StructuredTool。
"""

from __future__ import annotations

import json
from datetime import datetime, timedelta
from typing import Optional

from pydantic import BaseModel, Field

from app.log import logger
from app.models.rag import Document, KnowledgeBase

from .base import BaseToolProvider, adapt_to_langchain, adapt_to_llamaindex

# 列表查询最大返回条数
MAX_LIST_SIZE = 20


# ── LangChain 参数 Schema ────────────────────────────────────────

class KdDocMetaQueryArgs(BaseModel):
    """知识库文档元信息查询工具参数"""
    action: str = Field(
        ...,
        description=(
            "查询动作类型: "
            "'count' 返回文档总数; "
            "'list' 返回文档列表(最多20条); "
            "'stats' 返回按文档类型的分布统计"
        ),
    )
    doc_type_code: Optional[str] = Field(
        None, description="按文档类型筛选: feishu_doc / ppt / contract"
    )
    status: Optional[str] = Field(
        None, description="按状态筛选: completed / pending_review / failed 等"
    )
    days: Optional[int] = Field(
        None, description="最近N天内创建的文档，如 7 表示最近一周"
    )
    keyword: Optional[str] = Field(
        None, description="按文档标题关键词筛选（模糊匹配）"
    )


# ── 核心业务逻辑 ─────────────────────────────────────────────────

def _make_doc_meta_query_fn(kb_ids: list[int]):
    """工厂函数：生成元信息查询工具的核心异步函数"""

    async def kd_doc_meta_query(
        action: str = "count",
        doc_type_code: Optional[str] = None,
        status: Optional[str] = None,
        days: Optional[int] = None,
        keyword: Optional[str] = None,
    ) -> str:
        """查询知识库文档元信息（数量/列表/统计），返回 JSON 字符串"""
        try:
            # 基础过滤：属于指定知识库且未删除
            qs = Document.filter(
                knowledge_base_id__in=kb_ids,
                is_deleted=False,
            )

            # 可选筛选条件
            if doc_type_code:
                qs = qs.filter(doc_type_code=doc_type_code)
            if status:
                qs = qs.filter(status=status)
            if days:
                since = datetime.now() - timedelta(days=days)
                qs = qs.filter(created_at__gte=since)
            if keyword:
                qs = qs.filter(title__icontains=keyword)

            if action == "count":
                total = await qs.count()
                return json.dumps({"total": total}, ensure_ascii=False)

            elif action == "list":
                total = await qs.count()
                docs = await qs.order_by("-updated_at").limit(MAX_LIST_SIZE).values(
                    "id", "title", "doc_type_code", "status", "created_at", "updated_at"
                )
                items = []
                for d in docs:
                    items.append({
                        "id": d["id"],
                        "title": d["title"],
                        "doc_type_code": d["doc_type_code"],
                        "status": d["status"],
                        "created_at": d["created_at"].strftime("%Y-%m-%d %H:%M") if d["created_at"] else None,
                        "updated_at": d["updated_at"].strftime("%Y-%m-%d %H:%M") if d["updated_at"] else None,
                    })
                result = {"total": total, "items": items}
                if total > MAX_LIST_SIZE:
                    result["hint"] = f"共 {total} 条，已展示最近 {MAX_LIST_SIZE} 条，可进一步筛选"
                return json.dumps(result, ensure_ascii=False)

            elif action == "stats":
                # 按 doc_type_code 分组统计
                all_docs = await qs.values_list("doc_type_code", flat=True)
                from collections import Counter
                counter = Counter(all_docs)
                stats = [{"doc_type_code": k, "count": v} for k, v in counter.items()]
                return json.dumps({
                    "total": sum(counter.values()),
                    "by_type": stats,
                }, ensure_ascii=False)

            else:
                return json.dumps({"error": f"不支持的 action: {action}"}, ensure_ascii=False)

        except Exception as e:
            logger.error("[KdDocMetaQuery] Error: %s", e)
            return json.dumps({"error": str(e)}, ensure_ascii=False)

    return kd_doc_meta_query


# ── 工具提供者 ────────────────────────────────────────────────────

class KdDocMetaToolProvider(BaseToolProvider):
    """知识库文档元信息查询工具提供者

    为 Agent 绑定的知识库集合构建一个统一的元信息查询工具。
    """

    TOOL_NAME = "kd_doc_meta_query"
    TOOL_DESC = (
        "查询知识库中文档的元信息。"
        "支持统计文档数量(action='count')、获取文档列表(action='list')、按类型分布统计(action='stats')。"
        "可选筛选条件：doc_type_code(文档类型)、status(状态)、days(最近N天)、keyword(标题关键词)。"
        "当用户询问'有多少文档/合同'、'列出最近的文件'、'按类型分布'等问题时使用此工具。"
    )

    async def build_llamaindex_tools(self, *, knowledge_bases: list[KnowledgeBase] = None, **kwargs) -> list:
        knowledge_bases = knowledge_bases or []
        if not knowledge_bases:
            return []
        kb_ids = [kb.id for kb in knowledge_bases]
        fn = _make_doc_meta_query_fn(kb_ids)
        tool = adapt_to_llamaindex(fn, self.TOOL_NAME, self.TOOL_DESC)
        logger.debug("[KdDocMeta] Built llamaindex tool for kb_ids=%s", kb_ids)
        return [tool]

    async def build_langchain_tools(self, *, knowledge_bases: list[KnowledgeBase] = None, **kwargs) -> list:
        knowledge_bases = knowledge_bases or []
        if not knowledge_bases:
            return []
        kb_ids = [kb.id for kb in knowledge_bases]
        fn = _make_doc_meta_query_fn(kb_ids)
        tool = adapt_to_langchain(fn, self.TOOL_NAME, self.TOOL_DESC, args_schema=KdDocMetaQueryArgs)
        logger.debug("[KdDocMeta] Built langchain tool for kb_ids=%s", kb_ids)
        return [tool]
