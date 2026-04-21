"""LLM / Embedding 模型构建器 — 从 RAGService 提取，供多服务复用"""

from app.models.rag import LLMProviderConfig
from app.settings import settings


def build_llm(config: LLMProviderConfig):
    """根据数据库配置动态构建 LLM 实例"""
    from llama_index.llms.openai_like import OpenAILike

    extra = config.extra_config or {}
    return OpenAILike(
        api_base=config.api_base_url,
        api_key=config.api_key,
        model=config.model_name,
        max_tokens=config.max_tokens,
        temperature=extra.get("temperature", 0.7),
        is_chat_model=True,
        context_window=8192,
        is_function_calling_model=True,
    )


def build_embed_model(config: LLMProviderConfig):
    """根据数据库配置动态构建 Embedding 模型"""
    from llama_index.embeddings.openai import OpenAIEmbedding

    return OpenAIEmbedding(
        api_base=config.api_base_url,
        api_key=config.api_key,
        model_name=config.model_name,
        embed_batch_size=10,
        dimensions=settings.DEFAULT_EMBEDDING_DIMENSION,
    )
