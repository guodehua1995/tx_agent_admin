"""切片层 (slicing) 单元测试

测试范围:
- SLICING_HANDLERS 注册表 + register_handler 装饰器
- run_slicing 分发函数
- SlicingResult 数据类
- BaseSlicingHandler.process 抽象签名
- BaseSlicingHandler.call_llm 流式调用 + 重试 + 超时
- MeetingNotesSlicingHandler / PartnerProfileSlicingHandler.process
"""

import asyncio
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock, patch

import pytest


# ========== 注册表与分发 ==========


class TestRegistry:
    def test_handlers_registered(self):
        """内置处理器应在导入时完成注册"""
        from app.services.slicing import SLICING_HANDLERS
        from app.services.slicing.contract import ContractSlicingHandler
        from app.services.slicing.meeting_notes import MeetingNotesSlicingHandler
        from app.services.slicing.partner_profile import PartnerProfileSlicingHandler

        assert SLICING_HANDLERS["meeting_notes"] is MeetingNotesSlicingHandler
        assert SLICING_HANDLERS["partner_profile"] is PartnerProfileSlicingHandler
        assert SLICING_HANDLERS["contract"] is ContractSlicingHandler

    def test_register_handler_decorator(self):
        """register_handler 装饰器应将类注入到 SLICING_HANDLERS"""
        from app.services.slicing import SLICING_HANDLERS, register_handler

        @register_handler("__test_code__")
        class _Dummy:
            pass

        try:
            assert SLICING_HANDLERS["__test_code__"] is _Dummy
        finally:
            SLICING_HANDLERS.pop("__test_code__", None)


class TestRunSlicing:
    @pytest.mark.asyncio
    async def test_dispatches_to_registered_handler(self):
        """run_slicing 应实例化对应 handler 并调用 process"""
        from app.services.slicing import SLICING_HANDLERS, SlicingResult, run_slicing

        captured = {}

        class _Fake:
            def __init__(self, model_config):
                captured["model_config"] = model_config

            async def process(self, raw_content, pages=None):
                captured["raw_content"] = raw_content
                captured["pages"] = pages
                return SlicingResult(content="ok", prompt_used="p")

        SLICING_HANDLERS["__fake__"] = _Fake
        try:
            cfg = MagicMock()
            result = await run_slicing("__fake__", "raw text", cfg, pages=None)
        finally:
            SLICING_HANDLERS.pop("__fake__", None)

        assert isinstance(result, SlicingResult)
        assert result.content == "ok"
        assert captured["model_config"] is cfg
        assert captured["raw_content"] == "raw text"
        assert captured["pages"] is None

    @pytest.mark.asyncio
    async def test_unregistered_doc_type_raises(self):
        """未注册的 doc_type_code 应抛 ValueError"""
        from app.services.slicing import run_slicing

        with pytest.raises(ValueError, match="未注册的切片处理器"):
            await run_slicing("__no_such_type__", "content", MagicMock())


# ========== SlicingResult 数据类 ==========


class TestSlicingResult:
    def test_default_values(self):
        from app.services.slicing import SlicingResult

        r = SlicingResult(content="x")
        assert r.content == "x"
        assert r.prompt_used is None
        assert r.token_usage == {}

    def test_custom_values(self):
        from app.services.slicing import SlicingResult

        r = SlicingResult(content="c", prompt_used="prompt", token_usage={"total": 10})
        assert r.prompt_used == "prompt"
        assert r.token_usage == {"total": 10}


# ========== BaseSlicingHandler ==========


class TestBaseSlicingHandler:
    @pytest.mark.asyncio
    async def test_process_is_abstract(self):
        """基类 process 必须由子类实现"""
        from app.services.slicing.base import BaseSlicingHandler

        handler = BaseSlicingHandler(MagicMock())
        with pytest.raises(NotImplementedError):
            await handler.process("any")


def _make_model_config():
    cfg = MagicMock()
    cfg.api_base_url = "https://api.test/v1"
    cfg.api_key = "sk-x"
    cfg.model_name = "gpt-test"
    cfg.max_tokens = 1024
    cfg.extra_config = {"temperature": 0.2}
    return cfg


def _async_iter(items):
    """构造 astream_chat 返回的 async iterator (yield 一系列 chunk)"""

    async def _gen():
        for item in items:
            yield item

    return _gen()


class TestCallLLMStreaming:
    @pytest.mark.asyncio
    async def test_collects_deltas_into_full_text(self):
        """应将多个 delta 拼接为完整字符串"""
        from app.services.slicing.base import BaseSlicingHandler

        handler = BaseSlicingHandler(_make_model_config())

        chunks = [
            SimpleNamespace(delta="Hello, ", message=None),
            SimpleNamespace(delta="world", message=None),
            SimpleNamespace(delta="!", message=SimpleNamespace(content="Hello, world!")),
        ]

        mock_llm = MagicMock()
        mock_llm.astream_chat = AsyncMock(return_value=_async_iter(chunks))

        with patch("llama_index.llms.openai_like.OpenAILike", return_value=mock_llm):
            text = await handler.call_llm("sys", "user", timeout=5, max_retries=0)

        assert text == "Hello, world!"
        mock_llm.astream_chat.assert_awaited_once()

    @pytest.mark.asyncio
    async def test_falls_back_to_final_message_when_no_delta(self):
        """无 delta 时使用尾包 message.content"""
        from app.services.slicing.base import BaseSlicingHandler

        handler = BaseSlicingHandler(_make_model_config())

        chunks = [
            SimpleNamespace(delta=None, message=SimpleNamespace(content="final-only")),
        ]

        mock_llm = MagicMock()
        mock_llm.astream_chat = AsyncMock(return_value=_async_iter(chunks))

        with patch("llama_index.llms.openai_like.OpenAILike", return_value=mock_llm):
            text = await handler.call_llm("sys", "user", timeout=5, max_retries=0)

        assert text == "final-only"

    @pytest.mark.asyncio
    async def test_retries_then_succeeds(self):
        """首次失败、第二次成功；总调用次数 = 2"""
        from app.services.slicing.base import BaseSlicingHandler

        handler = BaseSlicingHandler(_make_model_config())

        ok_chunks = [SimpleNamespace(delta="ok", message=None)]

        call_count = {"n": 0}

        async def _astream(messages):
            call_count["n"] += 1
            if call_count["n"] == 1:
                raise RuntimeError("network glitch")
            return _async_iter(ok_chunks)

        mock_llm = MagicMock()
        mock_llm.astream_chat = _astream

        with patch("llama_index.llms.openai_like.OpenAILike", return_value=mock_llm), \
             patch("app.services.slicing.base.asyncio.sleep", AsyncMock()):
            text = await handler.call_llm("sys", "user", timeout=5, max_retries=1)

        assert text == "ok"
        assert call_count["n"] == 2

    @pytest.mark.asyncio
    async def test_exhausted_retries_raises_llm_call_error(self):
        """重试耗尽后抛 LLMCallError"""
        from app.services.slicing.base import BaseSlicingHandler, LLMCallError

        handler = BaseSlicingHandler(_make_model_config())

        async def _always_fail(messages):
            raise RuntimeError("boom")

        mock_llm = MagicMock()
        mock_llm.astream_chat = _always_fail

        with patch("llama_index.llms.openai_like.OpenAILike", return_value=mock_llm), \
             patch("app.services.slicing.base.asyncio.sleep", AsyncMock()):
            with pytest.raises(LLMCallError):
                await handler.call_llm("sys", "user", timeout=5, max_retries=1)

    @pytest.mark.asyncio
    async def test_timeout_triggers_retry(self):
        """单次超时按重试策略再尝试"""
        from app.services.slicing.base import BaseSlicingHandler, LLMCallError

        handler = BaseSlicingHandler(_make_model_config())

        async def _slow(messages):
            await asyncio.sleep(10)
            return _async_iter([])

        mock_llm = MagicMock()
        mock_llm.astream_chat = _slow

        with patch("llama_index.llms.openai_like.OpenAILike", return_value=mock_llm), \
             patch("app.services.slicing.base.asyncio.sleep", AsyncMock()):
            with pytest.raises(LLMCallError):
                # timeout=0.01 → 必超时；max_retries=0 → 仅 1 次尝试
                await handler.call_llm("sys", "user", timeout=0.01, max_retries=0)

    @pytest.mark.asyncio
    async def test_empty_response_raises_llm_call_error(self):
        """LLM 返回空字符串视为失败"""
        from app.services.slicing.base import BaseSlicingHandler, LLMCallError

        handler = BaseSlicingHandler(_make_model_config())

        mock_llm = MagicMock()
        mock_llm.astream_chat = AsyncMock(return_value=_async_iter([]))

        with patch("llama_index.llms.openai_like.OpenAILike", return_value=mock_llm), \
             patch("app.services.slicing.base.asyncio.sleep", AsyncMock()):
            with pytest.raises(LLMCallError):
                await handler.call_llm("sys", "user", timeout=5, max_retries=0)


# ========== 具体处理器 ==========


class TestMeetingNotesSlicingHandler:
    @pytest.mark.asyncio
    async def test_process_calls_llm_and_returns_result(self):
        from app.services.slicing import SlicingResult
        from app.services.slicing.meeting_notes import (
            SYSTEM_PROMPT,
            MeetingNotesSlicingHandler,
        )

        handler = MeetingNotesSlicingHandler(_make_model_config())

        with patch.object(
            MeetingNotesSlicingHandler,
            "call_llm",
            new=AsyncMock(return_value="# 整理后的会议纪要"),
        ) as mock_call:
            result = await handler.process("原始会议内容")

        assert isinstance(result, SlicingResult)
        assert result.content == "# 整理后的会议纪要"
        assert result.prompt_used == SYSTEM_PROMPT
        # 第一参为 system prompt，第二参为 user content
        args, _ = mock_call.call_args
        assert args[0] == SYSTEM_PROMPT
        assert args[1] == "原始会议内容"


class TestPartnerProfileSlicingHandler:
    @pytest.mark.asyncio
    async def test_process_calls_llm_and_returns_result(self):
        from app.services.slicing import SlicingResult
        from app.services.slicing.partner_profile import (
            SYSTEM_PROMPT,
            PartnerProfileSlicingHandler,
        )

        handler = PartnerProfileSlicingHandler(_make_model_config())

        with patch.object(
            PartnerProfileSlicingHandler,
            "call_llm",
            new=AsyncMock(return_value="# 合作伙伴画像"),
        ):
            result = await handler.process("公司原始信息")

        assert isinstance(result, SlicingResult)
        assert result.content == "# 合作伙伴画像"
        assert result.prompt_used == SYSTEM_PROMPT
