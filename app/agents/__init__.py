"""
LangChain Agent 统一管理模块

提供 Agent 的注册、配置、执行等核心功能
"""

from .base import BaseAgent
from .registry import AgentRegistry, register_agent
from .executor import agent_executor

# 导入所有 Agent 实现以触发注册
from . import agents

__all__ = [
    "BaseAgent",
    "AgentRegistry",
    "register_agent",
    "agent_executor",
]
