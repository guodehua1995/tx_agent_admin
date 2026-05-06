"""
文档模板工具

负责将 DocTemplate 构建为 Agent 可用的 FunctionTool / StructuredTool,
当 Agent 在对话中判断需要生成文档时自动调用。

同时输出 LlamaIndex FunctionTool 和 LangChain StructuredTool。
"""

from __future__ import annotations

import json
import logging
from typing import Optional

from pydantic import BaseModel, Field

from app.log import logger
from app.models.rag import DocTemplate

from .base import BaseToolProvider, adapt_to_langchain, adapt_to_llamaindex


# ── LangChain 参数 Schema ────────────────────────────────────────

class GenerateDocArgs(BaseModel):
    """文档生成工具参数"""
    doc_name: str = Field(..., description="文档标题名称")
    filled_content: str = Field(..., description="已根据模板格式填充好内容的完整Markdown文本")


# ── 核心业务逻辑（与框架无关）─────────────────────────────────────

async def _get_feishu_access_token() -> str:
    """从 GlobalConfig 获取飞书 access_token"""
    from app.controllers.feishu_bot import feishu_bot_controller
    from app.models.global_config import GlobalConfig
    from app.services.feishu_service import feishu_service

    config = await GlobalConfig.filter(config_key="feishu_pull_bot").first()
    if not config:
        raise RuntimeError("未配置 feishu_pull_bot，请在全局配置中设置")
    bot = await feishu_bot_controller.get_by_app_id(app_id=config.config_value)
    return await feishu_service.get_tenant_access_token(bot.app_id, bot.app_secret)


def _make_generate_doc_fn(template: DocTemplate):
    """工厂函数：为单个模板生成文档创建工具函数"""

    async def generate_document(doc_name: str, filled_content: str) -> str:
        """根据模板生成飞书云文档。

        Args:
            doc_name: 文档标题名称
            filled_content: 已根据模板格式填充好内容的完整Markdown文本

        Returns:
            生成结果的JSON字符串，包含文档URL或错误信息
        """
        from app.services.feishu_service import feishu_service

        try:
            access_token = await _get_feishu_access_token()
            doc_url = await feishu_service.import_markdown_to_folder(
                folder_token=template.folder_token,
                title=doc_name,
                markdown_content=filled_content,
                access_token=access_token,
            )
            logger.info(
                "[DocTemplateTool] Generated doc: template=%s, name=%s, url=%s",
                template.name, doc_name, doc_url,
            )
            return json.dumps(
                {"success": True, "url": doc_url, "doc_name": doc_name},
                ensure_ascii=False,
            )
        except Exception as e:
            logger.error("[DocTemplateTool] Generate error: %s", e)
            return json.dumps(
                {"success": False, "error": str(e)},
                ensure_ascii=False,
            )

    return generate_document


def _build_tool_meta(template: DocTemplate) -> tuple[str, str]:
    """构建工具名称和描述"""
    tool_name = f"generate_doc_{template.id}"
    naming_hint = f"命名规则: {template.naming_format}。" if template.naming_format else ""
    tool_desc = (
        f"使用「{template.name}」模板生成飞书云文档。"
        f"{template.description} "
        f"{naming_hint}"
        f"调用时需提供 doc_name（文档标题）和 filled_content（按以下模板格式填充的完整Markdown内容）。"
        f"\n\n模板格式:\n{template.markdown_content[:1500]}"
    )
    return tool_name, tool_desc


# ── 工具提供者 ────────────────────────────────────────────────────

class DocTemplateToolProvider(BaseToolProvider):
    """文档模板工具提供者

    每个模板生成一个独立的工具，工具描述中包含模板的用途说明和格式要求，
    以便 Agent (LLM) 自行判断何时调用。
    """

    def __init__(self, templates: list[DocTemplate]):
        self.templates = templates

    async def build_llamaindex_tools(self, **kwargs) -> list:
        tools = []
        for tpl in self.templates:
            fn = _make_generate_doc_fn(tpl)
            name, desc = _build_tool_meta(tpl)
            tools.append(adapt_to_llamaindex(fn, name, desc))
            logger.debug(f"[DocTemplateTool] Built llamaindex tool: {name} for template={tpl.name}")
        return tools

    async def build_langchain_tools(self, **kwargs) -> list:
        tools = []
        for tpl in self.templates:
            fn = _make_generate_doc_fn(tpl)
            name, desc = _build_tool_meta(tpl)
            tools.append(adapt_to_langchain(fn, name, desc, args_schema=GenerateDocArgs))
            logger.debug(f"[DocTemplateTool] Built langchain tool: {name} for template={tpl.name}")
        return tools
