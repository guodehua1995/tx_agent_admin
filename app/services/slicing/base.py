import asyncio
import logging
from typing import Optional, Type, TypeVar

from pydantic import BaseModel

from app.models.rag import DocumentPage, LLMProviderConfig

from . import SlicingResult

logger = logging.getLogger(__name__)

T = TypeVar("T", bound=BaseModel)

# LLM 调用默认参数
DEFAULT_LLM_TIMEOUT = 120     # 单次调用超时（秒）
DEFAULT_LLM_MAX_RETRIES = 2   # 额外重试次数（总尝试 = 1 + retries）


class LLMCallError(RuntimeError):
    """LLM 调用在重试耗尽后仍失败"""


class BaseSlicingHandler:
    """切片处理基类"""

    def __init__(self, model_config: LLMProviderConfig):
        self.model_config = model_config
        # 自动构建轻量模型配置（同渠道，不同模型）
        from copy import copy
        self.lite_model_config = copy(model_config)
        self.lite_model_config.model_name = self._get_lite_model_name()

    @staticmethod
    def _get_lite_model_name() -> str:
        """获取轻量级模型名称，从 settings 读取"""
        from app.settings.config import settings
        return settings.LITE_LLM_MODEL_NAME

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

    async def call_llm_structured(
        self,
        system_prompt: str,
        user_content: str,
        output_model: Type[T],
        use_lite: bool = False,
        timeout: int = DEFAULT_LLM_TIMEOUT,
        max_retries: int = DEFAULT_LLM_MAX_RETRIES,
    ) -> T:
        """调用 LLM 并返回结构化 Pydantic 对象（LangChain with_structured_output）。

        - 使用 ChatOpenAI + Pydantic schema 强制输出合法 JSON；
        - use_lite=True 时使用轻量级模型（同渠道，LITE_LLM_MODEL_NAME），速度快、成本低；
        - 自动重试 + 超时控制；
        - 返回已填充的 Pydantic 模型实例，无需手动 json.loads。
        """
        from langchain_openai import ChatOpenAI
        from langchain_core.messages import SystemMessage, HumanMessage

        config = self.lite_model_config if use_lite else self.model_config
        extra = config.extra_config or {}
        llm = ChatOpenAI(
            base_url=config.api_base_url,
            api_key=config.api_key,
            model=config.model_name,
            max_tokens=config.max_tokens,
            temperature=extra.get("temperature", 0.3),
        )
        structured_llm = llm.with_structured_output(output_model)

        messages = [
            SystemMessage(content=system_prompt),
            HumanMessage(content=user_content),
        ]

        async def _invoke() -> T:
            return await structured_llm.ainvoke(messages)

        last_err: Optional[BaseException] = None
        total_attempts = max_retries + 1
        for attempt in range(1, total_attempts + 1):
            try:
                result = await asyncio.wait_for(_invoke(), timeout=timeout)
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
                    "[LLM-structured] call failed (attempt %d/%d, %s), retry in %ds",
                    attempt, total_attempts, err_repr, backoff,
                )
                await asyncio.sleep(backoff)
            else:
                logger.exception(
                    "[LLM-structured] call exhausted retries (%d attempts), last error: %s",
                    total_attempts, err_repr,
                )

        raise LLMCallError(f"LLM structured call failed after {total_attempts} attempts: {last_err}")
