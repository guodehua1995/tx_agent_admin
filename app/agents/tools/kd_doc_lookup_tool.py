"""
知识库文档按名检索与摘要查询工具

根据用户提供的文档名称，对文档标题进行模糊匹配，
返回匹配文档的摘要信息和访问链接。

仅基于 Document 表 title 字段做 ILIKE 模糊匹配，
不涉及 JSON 字段或向量库查询。

同时输出 LlamaIndex FunctionTool 和 LangChain StructuredTool。
"""

from __future__ import annotations

import json
from typing import Optional

from pydantic import BaseModel, Field

from app.log import logger
from app.models.rag import Document, KnowledgeBase

from .base import BaseToolProvider, adapt_to_langchain, adapt_to_llamaindex

# 按名检索最多返回条数
MAX_LOOKUP_SIZE = 5


# ── LangChain 参数 Schema ────────────────────────────────────────

class KdDocLookupArgs(BaseModel):
    """文档按名检索与摘要查询工具参数"""
    keyword: str = Field(..., description="文档名称关键词（用于标题模糊匹配）")


# ── 核心业务逻辑 ─────────────────────────────────────────────────

def _make_doc_lookup_fn(kb_ids: list[int]):
    """工厂函数：生成按名检索工具的核心异步函数"""

    async def kd_doc_lookup(keyword: str) -> str:
        """根据文档标题关键词模糊匹配，返回文档摘要和链接信息的 JSON 字符串"""
        try:
            if not keyword or not keyword.strip():
                return json.dumps({"error": "请提供文档名称关键词"}, ensure_ascii=False)

            keyword = keyword.strip()

            # 标题模糊匹配（ILIKE），仅查已完成且未删除的文档
            docs = await Document.filter(
                knowledge_base_id__in=kb_ids,
                is_deleted=False,
                title__icontains=keyword,
            ).order_by("-updated_at").limit(MAX_LOOKUP_SIZE).values(
                "id", "title", "summary", "source_type", "source_meta",
                "doc_type_code", "created_at", "updated_at"
            )

            if not docs:
                return json.dumps({
                    "matched": 0,
                    "message": f"未找到标题包含「{keyword}」的文档，可尝试使用语义检索工具进行全库搜索。",
                }, ensure_ascii=False)

            items = []
            for d in docs:
                # 提取访问链接：优先从 source_meta 获取
                access_url = None
                meta = d.get("source_meta") or {}
                if d["source_type"] == "feishu_doc":
                    access_url = meta.get("url") or meta.get("doc_url")
                elif d["source_type"] == "web_url":
                    access_url = meta.get("url")
                # file_upload 类型暂无外部链接

                items.append({
                    "id": d["id"],
                    "title": d["title"],
                    "summary": d["summary"] or "暂无摘要",
                    "source_type": d["source_type"],
                    "doc_type_code": d["doc_type_code"],
                    "access_url": access_url,
                    "created_at": d["created_at"].strftime("%Y-%m-%d %H:%M") if d["created_at"] else None,
                })

            return json.dumps({
                "matched": len(items),
                "items": items,
            }, ensure_ascii=False)

        except Exception as e:
            logger.error("[KdDocLookup] Error: %s", e)
            return json.dumps({"error": str(e)}, ensure_ascii=False)

    return kd_doc_lookup


# ── 工具提供者 ────────────────────────────────────────────────────

class KdDocLookupToolProvider(BaseToolProvider):
    """文档按名检索与摘要查询工具提供者

    根据文档名称模糊匹配，返回文档摘要和访问链接。
    当标题匹配无结果时，建议 Agent 回退到语义检索工具。
    """

    TOOL_NAME = "kd_doc_lookup"
    TOOL_DESC = (
        "根据文档名称关键词查找文档，返回文档的摘要概述和访问链接。"
        "当用户提到具体的文档名称（如书名号《》包裹的名称、引号包裹的名称、或已知文件名片段），"
        "或者要求查看某文档的概要/摘要/链接时，使用此工具。"
        "如果此工具未找到匹配文档，应转用语义检索工具进行全库搜索。"
    )

    async def build_llamaindex_tools(self, *, knowledge_bases: list[KnowledgeBase] = None, **kwargs) -> list:
        knowledge_bases = knowledge_bases or []
        if not knowledge_bases:
            return []
        kb_ids = [kb.id for kb in knowledge_bases]
        fn = _make_doc_lookup_fn(kb_ids)
        tool = adapt_to_llamaindex(fn, self.TOOL_NAME, self.TOOL_DESC)
        logger.debug("[KdDocLookup] Built llamaindex tool for kb_ids=%s", kb_ids)
        return [tool]

    async def build_langchain_tools(self, *, knowledge_bases: list[KnowledgeBase] = None, **kwargs) -> list:
        knowledge_bases = knowledge_bases or []
        if not knowledge_bases:
            return []
        kb_ids = [kb.id for kb in knowledge_bases]
        fn = _make_doc_lookup_fn(kb_ids)
        tool = adapt_to_langchain(fn, self.TOOL_NAME, self.TOOL_DESC, args_schema=KdDocLookupArgs)
        logger.debug("[KdDocLookup] Built langchain tool for kb_ids=%s", kb_ids)
        return [tool]
