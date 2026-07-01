"""LLM / Embedding 模型构建器 — 从 RAGService 提取，供多服务复用"""

from __future__ import annotations

from typing import Any, List

import httpx
from llama_index.core.base.embeddings.base import BaseEmbedding
from pydantic import Field, PrivateAttr

from app.log import logger
from app.models.rag import LLMProviderConfig
from app.settings import settings


def build_llm(config: LLMProviderConfig):
    """根据数据库配置动态构建 LLM 实例"""
    from llama_index.llms.openai_like import OpenAILike

    extra = config.extra_config or {}
    # context_window 优先从 extra_config 读取，未配置时兜底到 max_tokens
    context_window = extra.get("context_window") or config.max_tokens
    return OpenAILike(
        api_base=config.api_base_url,
        api_key=config.api_key,
        model=config.model_name,
        max_tokens=config.max_tokens,
        temperature=extra.get("temperature", 0.7),
        is_chat_model=True,
        context_window=context_window,
        is_function_calling_model=True,
    )


# ============================================================
# 多模态 Embedding 适配器（火山引擎 Ark /embeddings/multimodal）
# ============================================================


class MultimodalEmbedding(BaseEmbedding):
    """兼容火山引擎 Ark 多模态 Embedding 接口的自定义 Embedding 模型

    请求格式:
        POST {api_base}
        {"model": "ep-xxx", "input": [{"type": "text", "text": "..."}]}

    与标准 OpenAI /embeddings 的区别:
        - input 是对象数组，每个元素需指定 type
        - URL 路径为 /embeddings/multimodal（由用户在 api_base_url 中配置）
    """

    api_base: str = Field(description="API base URL (含完整路径，如 .../embeddings/multimodal)")
    api_key: str = Field(description="API Key")
    model_name: str = Field(description="模型接入点 ID")
    _dimensions: int = PrivateAttr(default=2560)

    def __init__(self, api_base: str, api_key: str, model_name: str, dimensions: int = 2560, **kwargs: Any):
        super().__init__(
            model_name=model_name,
            api_base=api_base.rstrip("/"),
            api_key=api_key,
            **kwargs,
        )
        self._dimensions = dimensions

    def _build_payload(self, texts: List[str]) -> List[dict]:
        """构建批量请求（每次一条文本，多模态格式）"""
        return [{"type": "text", "text": t} for t in texts]

    async def _call_api(self, texts: List[str]) -> List[List[float]]:
        """调用多模态 Embedding 接口（逐条发请求）

        Ark 多模态接口响应格式:
            {"created": ..., "data": {"embedding": [...]}}
        """
        embeddings = []
        async with httpx.AsyncClient(timeout=60) as client:
            for text in texts:
                payload = {
                    "model": self.model_name,
                    "input": [{"type": "text", "text": text}],
                }
                resp = await client.post(
                    self.api_base,
                    json=payload,
                    headers={
                        "Authorization": f"Bearer {self.api_key}",
                        "Content-Type": "application/json",
                    },
                )
                resp.raise_for_status()
                data = resp.json()
                embeddings.append(data["data"]["embedding"])
        return embeddings

    def _call_api_sync(self, texts: List[str]) -> List[List[float]]:
        """同步调用多模态 Embedding 接口（逐条发请求）"""
        embeddings = []
        with httpx.Client(timeout=60) as client:
            for text in texts:
                payload = {
                    "model": self.model_name,
                    "input": [{"type": "text", "text": text}],
                }
                resp = client.post(
                    self.api_base,
                    json=payload,
                    headers={
                        "Authorization": f"Bearer {self.api_key}",
                        "Content-Type": "application/json",
                    },
                )
                resp.raise_for_status()
                data = resp.json()
                embeddings.append(data["data"]["embedding"])
        return embeddings

    # ── llama_index BaseEmbedding 必须实现的方法 ──

    def _get_text_embedding(self, text: str) -> List[float]:
        return self._call_api_sync([text])[0]

    def _get_query_embedding(self, query: str) -> List[float]:
        return self._get_text_embedding(query)

    async def _aget_text_embedding(self, text: str) -> List[float]:
        result = await self._call_api([text])
        return result[0]

    async def _aget_query_embedding(self, query: str) -> List[float]:
        return await self._aget_text_embedding(query)


# ============================================================
# 构建器
# ============================================================


def _is_multimodal_url(url: str) -> bool:
    """判断 URL 是否指向多模态 Embedding 接口"""
    return "multimodal" in url.lower()


def build_embed_model(config: LLMProviderConfig):
    """根据数据库配置动态构建 Embedding 模型

    自动识别 api_base_url:
      - 含 'multimodal' → 使用 MultimodalEmbedding（火山 Ark 多模态）
      - 否则 → 使用标准 OpenAIEmbedding
    """
    if _is_multimodal_url(config.api_base_url):
        logger.info(f"[EmbedBuilder] 使用多模态 Embedding: {config.model_name}")
        return MultimodalEmbedding(
            api_base=config.api_base_url,
            api_key=config.api_key,
            model_name=config.model_name,
            dimensions=settings.DEFAULT_EMBEDDING_DIMENSION,
        )

    from llama_index.embeddings.openai import OpenAIEmbedding

    return OpenAIEmbedding(
        api_base=config.api_base_url,
        api_key=config.api_key,
        model_name=config.model_name,
        embed_batch_size=10,
        dimensions=settings.DEFAULT_EMBEDDING_DIMENSION,
    )
