"""
Agent 工具基类与双框架适配器

每个工具提供者需继承 BaseToolProvider，实现核心逻辑并同时输出
LlamaIndex FunctionTool 和 LangChain StructuredTool。
"""

from __future__ import annotations

from abc import ABC, abstractmethod
from typing import Any, Callable, Coroutine, List, Optional, Type

from pydantic import BaseModel, Field


# ── 双框架适配函数 ──────────────────────────────────────────────

def adapt_to_llamaindex(
    fn: Callable[..., Coroutine],
    name: str,
    description: str,
) -> Any:
    """将异步函数包装为 LlamaIndex FunctionTool"""
    from llama_index.core.tools import FunctionTool

    return FunctionTool.from_defaults(fn=fn, name=name, description=description)


def adapt_to_langchain(
    fn: Callable[..., Coroutine],
    name: str,
    description: str,
    args_schema: Optional[Type[BaseModel]] = None,
) -> Any:
    """将异步函数包装为 LangChain StructuredTool"""
    from langchain_core.tools import StructuredTool

    kwargs: dict = {"coroutine": fn, "name": name, "description": description}
    if args_schema is not None:
        kwargs["args_schema"] = args_schema
    return StructuredTool.from_function(**kwargs)


# ── 工具提供者基类 ──────────────────────────────────────────────

class BaseToolProvider(ABC):
    """Agent 工具提供者基类

    子类需实现:
        - _build_core_functions() -> list[CoreToolDef]  定义核心逻辑
        - build_llamaindex_tools(**kwargs) -> list       输出 LlamaIndex 工具
        - build_langchain_tools(**kwargs) -> list        输出 LangChain 工具
    """

    @abstractmethod
    async def build_llamaindex_tools(self, **kwargs) -> list:
        """构建 LlamaIndex FunctionTool 列表"""
        ...

    @abstractmethod
    async def build_langchain_tools(self, **kwargs) -> list:
        """构建 LangChain StructuredTool 列表"""
        ...
