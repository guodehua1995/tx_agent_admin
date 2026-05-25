"""
Agent 执行引擎

负责创建 LLM 实例并执行 Agent
"""

from langchain_openai import ChatOpenAI

from .base import BaseAgent
from .config import AgentConfig


class AgentExecutor:
    """Agent 执行器"""

    def __init__(self, config: AgentConfig = None):
        self.config = config or AgentConfig.from_settings()
        self._llm_cache = {}

    def get_llm(self, agent_name: str = None):
        """获取或创建 LLM 实例（带缓存）"""
        cache_key = agent_name or "default"
        if cache_key not in self._llm_cache:
            self._llm_cache[cache_key] = self._create_llm()
        return self._llm_cache[cache_key]

    def _create_llm(self):
        """创建 LLM 实例"""
        if self.config.llm.provider == "openai":
            return ChatOpenAI(
                model=self.config.llm.model_name,
                api_key=self.config.llm.api_key,
                base_url=self.config.llm.base_url,
                temperature=self.config.llm.temperature,
                max_tokens=self.config.llm.max_tokens,
                # Qwen3 系列模型默认开启思考模式，响应内容在 reasoning_content 中，
                # 导致 content 字段为空。此处显式关闭思考模式。
                extra_body={"enable_thinking": False},
            )
        # 可扩展其他 provider
        raise ValueError(f"Unsupported LLM provider: {self.config.llm.provider}")

    async def execute(self, agent_name: str, input_data: dict, **kwargs):
        """执行指定 Agent"""
        from .registry import AgentRegistry

        agent_class = AgentRegistry.get(agent_name)
        llm = self.get_llm(agent_name)
        agent = agent_class(llm=llm)

        return await agent.execute(input_data, **kwargs)


# 单例
agent_executor = AgentExecutor()
