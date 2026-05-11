"""
当前系统时间工具

提供 FunctionTool 供 Agent 在对话中获取服务器当前时间，
支持自定义时区和时间格式。

同时输出 LlamaIndex FunctionTool 和 LangChain StructuredTool。
"""

from __future__ import annotations

import json
from datetime import datetime, timezone
from typing import Optional

from pydantic import BaseModel, Field

from app.log import logger

from .base import BaseToolProvider, adapt_to_langchain, adapt_to_llamaindex

TOOL_NAME = "get_current_time"
TOOL_DESCRIPTION = (
    "获取当前系统时间。"
    "可选参数 tz_offset 为时区偏移小时数（如东八区填 8，UTC 填 0，默认东八区 8）；"
    "可选参数 fmt 为 strftime 格式字符串（默认 '%Y-%m-%d %H:%M:%S'）。"
    "适用场景：用户询问当前时间、需要在生成的内容中插入时间戳时使用此工具。"
)

DEFAULT_TZ_OFFSET = 8
DEFAULT_FMT = "%Y-%m-%d %H:%M:%S"


# ── LangChain 参数 Schema ────────────────────────────────────────

class CurrentTimeArgs(BaseModel):
    """当前时间工具参数"""
    tz_offset: Optional[int] = Field(DEFAULT_TZ_OFFSET, description="时区偏移小时数（如东八区填 8，UTC 填 0），默认 8")
    fmt: Optional[str] = Field(DEFAULT_FMT, description="strftime 格式字符串，默认 '%Y-%m-%d %H:%M:%S'")


# ── 核心业务逻辑（与框架无关）─────────────────────────────────────

async def get_current_time(
    tz_offset: Optional[int] = DEFAULT_TZ_OFFSET,
    fmt: Optional[str] = DEFAULT_FMT,
) -> str:
    """获取当前系统时间。

    Args:
        tz_offset: 时区偏移小时数（如东八区填 8，UTC 填 0），默认 8
        fmt: strftime 格式字符串，默认 '%Y-%m-%d %H:%M:%S'

    Returns:
        JSON字符串，包含格式化时间字符串、时区、ISO 时间戳与星期信息
    """
    try:
        offset = DEFAULT_TZ_OFFSET if tz_offset is None else int(tz_offset)
        format_str = fmt or DEFAULT_FMT

        from datetime import timedelta
        tz = timezone(timedelta(hours=offset))
        now = datetime.now(tz)

        weekday_zh = ["星期一", "星期二", "星期三", "星期四", "星期五", "星期六", "星期日"][now.weekday()]
        result = {
            "success": True,
            "time": now.strftime(format_str),
            "iso": now.isoformat(),
            "tz_offset": offset,
            "weekday": weekday_zh,
        }
        logger.info(f"[CurrentTime] tz_offset={offset} time={result['time']}")
        return json.dumps(result, ensure_ascii=False)
    except Exception as e:
        logger.error(f"[CurrentTime] Error: {e}")
        return json.dumps({"success": False, "error": str(e)}, ensure_ascii=False)


# ── 工具提供者 ────────────────────────────────────────────────────

class CurrentTimeToolProvider(BaseToolProvider):
    """当前系统时间工具提供者"""

    async def build_llamaindex_tools(self, **kwargs) -> list:
        return [adapt_to_llamaindex(get_current_time, TOOL_NAME, TOOL_DESCRIPTION)]

    async def build_langchain_tools(self, **kwargs) -> list:
        return [adapt_to_langchain(get_current_time, TOOL_NAME, TOOL_DESCRIPTION, args_schema=CurrentTimeArgs)]


# 便捷实例
current_time_tool_provider = CurrentTimeToolProvider()
