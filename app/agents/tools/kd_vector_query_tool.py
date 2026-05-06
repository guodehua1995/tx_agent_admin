"""
知识库向量查询工具

为每个知识库构建一个可被 Agent 调用的查询工具，
支持向量检索并返回匹配文档片段。

同时输出 LlamaIndex FunctionTool 和 LangChain StructuredTool。
"""

from __future__ import annotations

import json
import logging
from typing import Optional

from pydantic import BaseModel, Field

from app.log import logger
from app.models.rag import KnowledgeBase, LLMProviderConfig
from app.services.llm_builder import build_embed_model

from .base import BaseToolProvider, adapt_to_langchain, adapt_to_llamaindex

METADATA_KEEP_KEYS = ["doc_id"]


# ── LangChain 参数 Schema ────────────────────────────────────────

class KdVectorQueryArgs(BaseModel):
    """知识库向量查询工具参数"""
    query: str = Field(..., description="检索关键词/问题")
    metadata_filters: Optional[dict] = Field(None, description="可选的元数据过滤条件")


# ── 核心业务逻辑（与框架无关）─────────────────────────────────────

def _make_kd_query_fn(retriever, kb_name: str, threshold: float):
    """工厂函数：生成知识库向量查询工具的核心异步函数"""

    async def kd_vector_query(query: str, metadata_filters: Optional[dict] = None) -> str:
        """在知识库中执行向量检索，返回匹配文档片段的 JSON 字符串"""
        from llama_index.core.indices.query.schema import QueryBundle
        from app.services.rag_node_processors import MetadataFilterPostProcessor

        try:
            nodes = await retriever.aretrieve(query)
            processor = MetadataFilterPostProcessor(METADATA_KEEP_KEYS)
            nodes = processor.postprocess_nodes(nodes, query_bundle=QueryBundle(query))

            results = []
            for node in nodes:
                score = getattr(node, "score", None)
                if score and score >= threshold:
                    node_obj = node.node if hasattr(node, "node") else node
                    node_text = node_obj.text if hasattr(node_obj, "text") else str(node_obj)
                    results.append({
                        "score": round(score, 4),
                        "text": node_text,
                        "metadata": node_obj.metadata,
                    })
            return json.dumps(results, ensure_ascii=False) if results else "[]"
        except Exception as e:
            logger.error("[KdVectorQuery] Error in %s: %s", kb_name, e)
            return json.dumps([{"error": str(e)}], ensure_ascii=False)

    return kd_vector_query


# ── 工具提供者 ────────────────────────────────────────────────────

class KdVectorQueryToolProvider(BaseToolProvider):
    """知识库向量查询工具提供者

    为每个知识库构建一个独立的查询工具，
    工具描述中包含知识库用途说明，以便 Agent 自行判断何时调用。
    """

    def __init__(self, vector_store):
        self._vector_store = vector_store

    async def _build_retriever(self, kb: KnowledgeBase, chat_model_config: LLMProviderConfig):
        """构建单个知识库的 retriever"""
        from llama_index.core import VectorStoreIndex
        from llama_index.core.vector_stores import ExactMatchFilter, MetadataFilters

        index = VectorStoreIndex.from_vector_store(
            vector_store=self._vector_store,
            embed_model=build_embed_model(
                await LLMProviderConfig.get(id=kb.embedding_model_id)
            ),
        )
        query_mode = "hybrid" if kb.retrieval_mode == "hybrid" else "default"
        return index.as_retriever(
            similarity_top_k=kb.similarity_top_k,
            filters=MetadataFilters(
                filters=[ExactMatchFilter(key="knowledge_base_id", value=str(kb.id))]
            ),
            vector_store_query_mode=query_mode,
        )

    def _build_tool_meta(self, kb: KnowledgeBase) -> tuple[str, str]:
        """构建工具名称和描述"""
        tool_name = f"kd_query_{kb.id}"
        kb_desc = kb.description or kb.name
        tool_desc = (
            f"在「{kb.name}」知识库中检索与问题相关的文档内容。"
            f"{kb_desc}。"
            f"输入参数 query 为检索关键词/问题，metadata_filters 为可选的元数据过滤条件。"
        )
        return tool_name, tool_desc

    async def build_llamaindex_tools(self, *, knowledge_bases: list[KnowledgeBase], **kwargs) -> list:
        tools = []
        for kb in knowledge_bases:
            retriever = await self._build_retriever(kb, kwargs.get("chat_model_config"))
            fn = _make_kd_query_fn(retriever, kb.name, kb.similarity_threshold)
            name, desc = self._build_tool_meta(kb)
            tools.append(adapt_to_llamaindex(fn, name, desc))
            logger.debug("[KdVectorQuery] Built llamaindex tool: %s for kb=%s", name, kb.name)
        return tools

    async def build_langchain_tools(self, *, knowledge_bases: list[KnowledgeBase], **kwargs) -> list:
        tools = []
        for kb in knowledge_bases:
            retriever = await self._build_retriever(kb, kwargs.get("chat_model_config"))
            fn = _make_kd_query_fn(retriever, kb.name, kb.similarity_threshold)
            name, desc = self._build_tool_meta(kb)
            tools.append(adapt_to_langchain(fn, name, desc, args_schema=KdVectorQueryArgs))
            logger.debug("[KdVectorQuery] Built langchain tool: %s for kb=%s", name, kb.name)
        return tools
