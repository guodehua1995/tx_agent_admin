"""
Agent 注册中心

统一管理所有 Agent 的注册和获取
"""

from typing import Dict, Type

from .base import BaseAgent


class AgentRegistry:
    """Agent 注册中心"""

    _agents: Dict[str, Type[BaseAgent]] = {}

    @classmethod
    def register(cls, agent_class: Type[BaseAgent]):
        """注册 Agent"""
        if not agent_class.name:
            raise ValueError("Agent must have a name")
        cls._agents[agent_class.name] = agent_class
        return agent_class

    @classmethod
    def get(cls, name: str) -> Type[BaseAgent]:
        """获取 Agent 类"""
        if name not in cls._agents:
            raise KeyError(f"Agent '{name}' not found")
        return cls._agents[name]

    @classmethod
    def list_agents(cls) -> Dict[str, Type[BaseAgent]]:
        """列出所有已注册 Agent"""
        return cls._agents.copy()


def register_agent(agent_class: Type[BaseAgent]) -> Type[BaseAgent]:
    """注册 Agent 的装饰器"""
    AgentRegistry.register(agent_class)
    return agent_class
