"""
网络内容读取工具

提供 FunctionTool 供 Agent 在对话中读取 URL 内容。
- 飞书文档 URL (https://my.feishu.cn/docx/*): 使用飞书 API 读取
- 其它 URL: 使用 trafilatura 提取网页正文

同时输出 LlamaIndex FunctionTool 和 LangChain StructuredTool。
"""

from __future__ import annotations

import json
import logging
import re
from typing import Optional

from pydantic import BaseModel, Field

from app.log import logger

from .base import BaseToolProvider, adapt_to_langchain, adapt_to_llamaindex

FEISHU_DOC_PATTERN = re.compile(r"https?://[^/]*feishu\.cn/(docx|wiki|sheets)/([A-Za-z0-9]+)")

TOOL_NAME = "read_url_content"
TOOL_DESCRIPTION = (
    "读取指定URL网页或文档的文本内容。"
    "输入参数 url 为完整的URL地址，返回该页面提取的纯文本内容。"
    "适用场景：用户提供了一个链接并希望了解其内容时使用此工具。"
)


# ── LangChain 参数 Schema ────────────────────────────────────────

class WebReaderArgs(BaseModel):
    """网络内容读取工具参数"""
    url: str = Field(..., description="要读取的完整URL地址（如 https://example.com/article 或 https://my.feishu.cn/docx/xxx）")


# ── 核心业务逻辑（与框架无关）─────────────────────────────────────

async def _read_feishu_doc(url: str) -> str:
    """通过飞书 API 读取飞书云文档内容"""
    from app.controllers.feishu_bot import feishu_bot_controller
    from app.models.global_config import GlobalConfig
    from app.services.feishu_service import feishu_service

    doc_token, doc_type = feishu_service.parse_feishu_url(url)

    config = await GlobalConfig.filter(config_key="feishu_pull_bot").first()
    if not config:
        return json.dumps({"success": False, "error": "未配置 feishu_pull_bot"}, ensure_ascii=False)

    bot = await feishu_bot_controller.get_by_app_id(app_id=config.config_value)
    access_token = await feishu_service.get_tenant_access_token(bot.app_id, bot.app_secret)
    content = await feishu_service.fetch_document_content(doc_token, doc_type, access_token)
    return content


async def _read_web_url(url: str) -> str:
    """通过 trafilatura 提取网页正文文本"""
    import httpx
    import trafilatura

    async with httpx.AsyncClient(timeout=30, follow_redirects=True) as client:
        resp = await client.get(url, headers={
            "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36"
        })
        resp.raise_for_status()
        html = resp.text

    text = trafilatura.extract(html, include_links=True, include_tables=True)
    if not text:
        from trafilatura import bare_extraction
        result = bare_extraction(html)
        text = result.get("text", "") if result else ""

    return text if text else "无法从该URL提取到有效文本内容"


async def read_url_content(url: str) -> str:
    """读取指定URL的文本内容。

    支持飞书云文档和普通网页。输入一个完整的URL地址，返回该页面的纯文本内容。

    Args:
        url: 要读取的完整URL地址（如 https://example.com/article 或 https://my.feishu.cn/docx/xxx）

    Returns:
        JSON字符串，包含 success 状态和提取的文本内容或错误信息
    """
    try:
        if not url or not url.startswith("http"):
            return json.dumps(
                {"success": False, "error": "请提供有效的URL地址（以http://或https://开头）"},
                ensure_ascii=False,
            )

        if FEISHU_DOC_PATTERN.search(url):
            content = await _read_feishu_doc(url)
        else:
            content = await _read_web_url(url)

        max_length = 8000
        if len(content) > max_length:
            content = content[:max_length] + f"\n\n...(内容已截断，原文共{len(content)}字符)"

        logger.info("[WebReader] Read URL: %s, content_length=%d", url, len(content))
        return json.dumps({"success": True, "url": url, "content": content}, ensure_ascii=False)

    except Exception as e:
        logger.error("[WebReader] Error reading URL %s: %s", url, e)
        return json.dumps({"success": False, "url": url, "error": str(e)}, ensure_ascii=False)


# ── 工具提供者 ────────────────────────────────────────────────────

class WebReaderToolProvider(BaseToolProvider):
    """网络内容读取工具提供者"""

    async def build_llamaindex_tools(self, **kwargs) -> list:
        return [adapt_to_llamaindex(read_url_content, TOOL_NAME, TOOL_DESCRIPTION)]

    async def build_langchain_tools(self, **kwargs) -> list:
        return [adapt_to_langchain(read_url_content, TOOL_NAME, TOOL_DESCRIPTION, args_schema=WebReaderArgs)]


# 便捷实例
web_reader_tool_provider = WebReaderToolProvider()
