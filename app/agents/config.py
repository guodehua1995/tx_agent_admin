"""
Agent 配置管理

从 settings 统一管理 LLM 配置
"""

from pydantic import BaseModel

from app.settings import settings


class LLMConfig(BaseModel):
    """LLM 配置"""

    provider: str = "openai"  # openai, azure, local 等
    model_name: str = "gpt-4"
    api_key: str = ""
    base_url: str = ""
    temperature: float = 0.7
    max_tokens: int = 4000


class AgentConfig(BaseModel):
    """Agent 全局配置"""

    llm: LLMConfig = LLMConfig()

    @classmethod
    def from_settings(cls) -> "AgentConfig":
        """从环境变量加载配置"""
        return cls(
            llm=LLMConfig(
                provider=settings.LLM_PROVIDER,
                model_name=settings.LLM_MODEL_NAME,
                api_key=settings.LLM_API_KEY,
                base_url=settings.LLM_BASE_URL,
                temperature=settings.LLM_TEMPERATURE,
                max_tokens=settings.LLM_MAX_TOKENS,
            )
        )
