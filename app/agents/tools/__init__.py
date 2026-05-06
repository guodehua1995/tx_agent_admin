"""
Agent 工具统一入口

提供 build_chat_tools() 一站式构建对话所需的所有工具，
支持 LlamaIndex 和 LangChain 双框架输出。
"""

from __future__ import annotations

from typing import Literal, Optional

from app.log import logger

from .base import BaseToolProvider, adapt_to_langchain, adapt_to_llamaindex
from .doc_template_tool import DocTemplateToolProvider
from .kd_vector_query_tool import KdVectorQueryToolProvider
from .web_reader_tool import WebReaderToolProvider

__all__ = [
    "BaseToolProvider",
    "adapt_to_llamaindex",
    "adapt_to_langchain",
    "build_chat_tools",
    "DocTemplateToolProvider",
    "KdVectorQueryToolProvider",
    "WebReaderToolProvider",
]


async def build_chat_tools(
    framework: Literal["llamaindex", "langchain"] = "llamaindex",
    *,
    vector_store=None,
    knowledge_bases: list = None,
    chat_model_config=None,
    doc_templates: list = None,
) -> list:
    """一站式构建对话所需的所有 Agent 工具

    Args:
        framework: 输出框架 - "llamaindex" 或 "langchain"
        vector_store: 向量存储实例（kd_vector_query 需要）
        knowledge_bases: 知识库列表
        chat_model_config: 聊天模型配置
        doc_templates: 文档模板列表（可选）

    Returns:
        工具列表（LlamaIndex FunctionTool 或 LangChain StructuredTool）
    """
    knowledge_bases = knowledge_bases or []
    tools = []

    # 1. 知识库向量查询工具
    if knowledge_bases and vector_store:
        kd_provider = KdVectorQueryToolProvider(vector_store)
        if framework == "llamaindex":
            tools.extend(await kd_provider.build_llamaindex_tools(
                knowledge_bases=knowledge_bases,
                chat_model_config=chat_model_config,
            ))
        else:
            tools.extend(await kd_provider.build_langchain_tools(
                knowledge_bases=knowledge_bases,
                chat_model_config=chat_model_config,
            ))

    # 2. 文档模板工具
    if doc_templates:
        tpl_provider = DocTemplateToolProvider(doc_templates)
        if framework == "llamaindex":
            tools.extend(await tpl_provider.build_llamaindex_tools())
        else:
            tools.extend(await tpl_provider.build_langchain_tools())

    # 3. 网络内容读取工具（默认始终添加）
    web_provider = WebReaderToolProvider()
    if framework == "llamaindex":
        tools.extend(await web_provider.build_llamaindex_tools())
    else:
        tools.extend(await web_provider.build_langchain_tools())

    return tools
