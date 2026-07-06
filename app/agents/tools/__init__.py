"""
Agent 工具统一入口

提供 build_chat_tools() 一站式构建对话所需的所有工具，
支持 LlamaIndex 和 LangChain 双框架输出。
"""

from __future__ import annotations

from typing import Literal, Optional

from app.log import logger

from .base import BaseToolProvider, adapt_to_langchain, adapt_to_llamaindex
from .current_time_tool import CurrentTimeToolProvider
from .doc_template_tool import DocTemplateToolProvider
from .kd_doc_lookup_tool import KdDocLookupToolProvider
from .kd_doc_meta_tool import KdDocMetaToolProvider
from .kd_vector_query_tool import KdVectorQueryToolProvider
from .web_reader_tool import WebReaderToolProvider
from .quotation_rule_tool import QuotationRuleToolProvider
from .contract_tools import (
    ContractSearchToolProvider,
    ContractStatsToolProvider,
    ContractClauseSearchToolProvider,
    ContractSummarySearchToolProvider,
    CompareClauseSummariesToolProvider,
    CompareClauseFulltextToolProvider,
    FindSimilarContractsToolProvider,
)

__all__ = [
    "BaseToolProvider",
    "adapt_to_llamaindex",
    "adapt_to_langchain",
    "build_chat_tools",
    "CurrentTimeToolProvider",
    "DocTemplateToolProvider",
    "KdDocLookupToolProvider",
    "KdDocMetaToolProvider",
    "KdVectorQueryToolProvider",
    "WebReaderToolProvider",
    "QuotationRuleToolProvider",
    "ContractSearchToolProvider",
    "ContractStatsToolProvider",
    "ContractClauseSearchToolProvider",
    "ContractSummarySearchToolProvider",
    "CompareClauseSummariesToolProvider",
    "CompareClauseFulltextToolProvider",
    "FindSimilarContractsToolProvider",
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

    # 2. 知识库文档元信息查询工具
    if knowledge_bases:
        meta_provider = KdDocMetaToolProvider()
        if framework == "llamaindex":
            tools.extend(await meta_provider.build_llamaindex_tools(
                knowledge_bases=knowledge_bases,
            ))
        else:
            tools.extend(await meta_provider.build_langchain_tools(
                knowledge_bases=knowledge_bases,
            ))

    # 3. 知识库文档按名检索与摘要查询工具
    if knowledge_bases:
        lookup_provider = KdDocLookupToolProvider()
        if framework == "llamaindex":
            tools.extend(await lookup_provider.build_llamaindex_tools(
                knowledge_bases=knowledge_bases,
            ))
        else:
            tools.extend(await lookup_provider.build_langchain_tools(
                knowledge_bases=knowledge_bases,
            ))

    # 4. 文档模板工具
    if doc_templates:
        tpl_provider = DocTemplateToolProvider(doc_templates)
        if framework == "llamaindex":
            tools.extend(await tpl_provider.build_llamaindex_tools())
        else:
            tools.extend(await tpl_provider.build_langchain_tools())

    # 5. 网络内容读取工具（默认始终添加）
    web_provider = WebReaderToolProvider()
    if framework == "llamaindex":
        tools.extend(await web_provider.build_llamaindex_tools())
    else:
        tools.extend(await web_provider.build_langchain_tools())

    # 6. 当前系统时间工具（默认始终添加）
    time_provider = CurrentTimeToolProvider()
    if framework == "llamaindex":
        tools.extend(await time_provider.build_llamaindex_tools())
    else:
        tools.extend(await time_provider.build_langchain_tools())

    # # 7. 报价规则查询工具 手动注释 打开前需要询问用户
    # quotation_provider = QuotationRuleToolProvider()
    # if framework == "llamaindex":
    #     tools.extend(await quotation_provider.build_llamaindex_tools())
    # else:
    #     tools.extend(await quotation_provider.build_langchain_tools())

    # 7. 合同管理工具
    contract_providers = [
        ContractSearchToolProvider(),
        ContractStatsToolProvider(),
        ContractClauseSearchToolProvider(),
        ContractSummarySearchToolProvider(),
        CompareClauseSummariesToolProvider(),
        CompareClauseFulltextToolProvider(),
        FindSimilarContractsToolProvider(),
    ]
    for provider in contract_providers:
        if framework == "llamaindex":
            tools.extend(await provider.build_llamaindex_tools())
        else:
            tools.extend(await provider.build_langchain_tools())

    return tools
