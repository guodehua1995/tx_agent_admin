import logging

from app.models.rag import LLMProviderConfig

from . import StructuringResult

logger = logging.getLogger(__name__)


class BaseStructuringHandler:
    """结构化处理基类"""

    def __init__(self, model_config: LLMProviderConfig):
        self.model_config = model_config

    async def process(self, raw_content: str) -> StructuringResult:
        raise NotImplementedError

    async def call_llm(self, system_prompt: str, user_content: str) -> str:
        """调用 LLM"""
        from llama_index.llms.openai_like import OpenAILike

        extra = self.model_config.extra_config or {}
        llm = OpenAILike(
            api_base=self.model_config.api_base_url,
            api_key=self.model_config.api_key,
            model=self.model_config.model_name,
            max_tokens=self.model_config.max_tokens,
            temperature=extra.get("temperature", 0.3),
            is_chat_model=True,
        )

        from llama_index.core.llms import ChatMessage

        messages = [
            ChatMessage(role="system", content=system_prompt),
            ChatMessage(role="user", content=user_content),
        ]
        response = await llm.achat(messages)
        return response.message.content
