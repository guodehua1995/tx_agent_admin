import asyncio
import logging
from typing import Optional

from app.models.rag import DocumentPage, LLMProviderConfig

from . import SlicingResult

logger = logging.getLogger(__name__)

# LLM 调用默认参数
DEFAULT_LLM_TIMEOUT = 120     # 单次调用超时（秒）
DEFAULT_LLM_MAX_RETRIES = 2   # 额外重试次数（总尝试 = 1 + retries）


class LLMCallError(RuntimeError):
    """LLM 调用在重试耗尽后仍失败"""


class BaseSlicingHandler:
    """切片处理基类"""

    def __init__(self, model_config: LLMProviderConfig):
        self.model_config = model_config

    async def process(
        self,
        raw_content: str,
        pages: Optional[list[DocumentPage]] = None,
    ) -> SlicingResult:
        raise NotImplementedError

    async def call_llm(
        self,
        system_prompt: str,
        user_content: str,
        timeout: int = DEFAULT_LLM_TIMEOUT,
        max_retries: int = DEFAULT_LLM_MAX_RETRIES,
    ) -> str:
        """调用 LLM（流式接收 + 超时控制 + 重试退避）。

        - 使用 astream_chat 逐块接收，避免长调用被中间代理/服务端超时断开；
        - asyncio.wait_for 控制单次调用总耗时；
        - 超时或其他异常按指数退避重试；耗尽后抛 LLMCallError 交上层决策。
        """
        from llama_index.core.llms import ChatMessage as LiChatMessage
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

        messages = [
            LiChatMessage(role="system", content=system_prompt),
            LiChatMessage(role="user", content=user_content),
        ]

        async def _stream_collect() -> str:
            response_gen = await llm.astream_chat(messages)
            chunks: list[str] = []
            final_message = ""
            async for resp in response_gen:
                delta = getattr(resp, "delta", None)
                if delta:
                    chunks.append(delta)
                # 尾包会携带完整 message，作为备选
                msg = getattr(resp, "message", None)
                if msg is not None and getattr(msg, "content", None):
                    final_message = msg.content
            return ("".join(chunks) or final_message).strip()

        last_err: Optional[BaseException] = None
        total_attempts = max_retries + 1
        for attempt in range(1, total_attempts + 1):
            try:
                result = await asyncio.wait_for(_stream_collect(), timeout=timeout)
                if not result:
                    raise LLMCallError("LLM returned empty response")
                return result
            except asyncio.TimeoutError as e:
                last_err = e
                err_repr = f"timeout({timeout}s)"
            except Exception as e:  # noqa: BLE001
                last_err = e
                err_repr = repr(e)

            if attempt < total_attempts:
                backoff = min(2 ** (attempt - 1), 10)
                logger.warning(
                    "[LLM] call failed (attempt %d/%d, %s), retry in %ds",
                    attempt, total_attempts, err_repr, backoff,
                )
                await asyncio.sleep(backoff)
            else:
                logger.exception(
                    "[LLM] call exhausted retries (%d attempts), last error: %s",
                    total_attempts, err_repr,
                )

        raise LLMCallError(f"LLM call failed after {total_attempts} attempts: {last_err}")
