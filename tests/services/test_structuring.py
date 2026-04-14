"""结构化策略模式单元测试

测试范围:
- 策略注册表机制
- 分发函数 run_structuring
- 处理器基类与子类
- 错误处理
"""

from unittest.mock import AsyncMock, MagicMock, patch

import pytest


# ========== 策略注册表 & 分发函数测试 ==========


class TestStructuringRegistry:
    """测试策略注册表机制"""

    def test_handlers_registered(self):
        """验证 meeting_notes 和 partner_profile 处理器已注册"""
        from app.services.structuring import STRUCTURING_HANDLERS

        assert "meeting_notes" in STRUCTURING_HANDLERS
        assert "partner_profile" in STRUCTURING_HANDLERS

    def test_register_handler_decorator(self):
        """验证 register_handler 装饰器能正确注册新处理器"""
        from app.services.structuring import STRUCTURING_HANDLERS, register_handler
        from app.services.structuring.base import BaseStructuringHandler

        @register_handler("test_type")
        class TestHandler(BaseStructuringHandler):
            async def process(self, raw_content):
                pass

        assert "test_type" in STRUCTURING_HANDLERS
        assert STRUCTURING_HANDLERS["test_type"] is TestHandler

        # 清理
        del STRUCTURING_HANDLERS["test_type"]

    def test_register_handler_overwrites(self):
        """验证相同 code 的处理器会被覆盖"""
        from app.services.structuring import STRUCTURING_HANDLERS, register_handler
        from app.services.structuring.base import BaseStructuringHandler

        @register_handler("overwrite_test")
        class Handler1(BaseStructuringHandler):
            async def process(self, raw_content):
                pass

        @register_handler("overwrite_test")
        class Handler2(BaseStructuringHandler):
            async def process(self, raw_content):
                pass

        assert STRUCTURING_HANDLERS["overwrite_test"] is Handler2

        # 清理
        del STRUCTURING_HANDLERS["overwrite_test"]


class TestRunStructuring:
    """测试 run_structuring 分发函数"""

    @pytest.mark.asyncio
    async def test_unknown_code_raises(self):
        """未注册的 code 应抛出 ValueError"""
        from app.services.structuring import run_structuring

        mock_config = MagicMock()
        with pytest.raises(ValueError, match="未注册的结构化处理器: unknown_type"):
            await run_structuring("unknown_type", "content", mock_config)

    @pytest.mark.asyncio
    async def test_dispatches_to_correct_handler(self):
        """验证根据 code 分发到正确的处理器"""
        from app.services.structuring import (
            STRUCTURING_HANDLERS,
            StructuringResult,
            register_handler,
            run_structuring,
        )
        from app.services.structuring.base import BaseStructuringHandler

        @register_handler("dispatch_test")
        class DispatchTestHandler(BaseStructuringHandler):
            async def process(self, raw_content):
                return StructuringResult(content=f"processed: {raw_content}", prompt_used="test_prompt")

        mock_config = MagicMock()
        result = await run_structuring("dispatch_test", "hello world", mock_config)

        assert result.content == "processed: hello world"
        assert result.prompt_used == "test_prompt"

        # 清理
        del STRUCTURING_HANDLERS["dispatch_test"]


# ========== StructuringResult 数据类测试 ==========


class TestStructuringResult:
    def test_default_values(self):
        from app.services.structuring import StructuringResult

        r = StructuringResult(content="test")
        assert r.content == "test"
        assert r.prompt_used is None
        assert r.token_usage == {}

    def test_custom_values(self):
        from app.services.structuring import StructuringResult

        r = StructuringResult(
            content="result",
            prompt_used="my prompt",
            token_usage={"prompt_tokens": 100, "completion_tokens": 50},
        )
        assert r.content == "result"
        assert r.prompt_used == "my prompt"
        assert r.token_usage["prompt_tokens"] == 100


# ========== BaseStructuringHandler 测试 ==========


class TestBaseStructuringHandler:
    def test_init_stores_config(self):
        from app.services.structuring.base import BaseStructuringHandler

        mock_config = MagicMock()
        handler = BaseStructuringHandler(mock_config)
        assert handler.model_config is mock_config

    @pytest.mark.asyncio
    async def test_process_raises_not_implemented(self):
        from app.services.structuring.base import BaseStructuringHandler

        mock_config = MagicMock()
        handler = BaseStructuringHandler(mock_config)
        with pytest.raises(NotImplementedError):
            await handler.process("content")

    @pytest.mark.asyncio
    async def test_call_llm_constructs_and_calls(self):
        """验证 call_llm 正确构建 LLM 并发送消息"""
        import sys

        from app.services.structuring.base import BaseStructuringHandler

        mock_config = MagicMock()
        mock_config.api_base_url = "http://test.api"
        mock_config.api_key = "test-key"
        mock_config.model_name = "test-model"
        mock_config.max_tokens = 2048
        mock_config.extra_config = {"temperature": 0.5}

        handler = BaseStructuringHandler(mock_config)

        mock_response = MagicMock()
        mock_response.message.content = "LLM result"

        # 懒导入的依赖需要通过 sys.modules 注入 mock
        mock_openai_like_mod = MagicMock()
        mock_core_llms_mod = MagicMock()

        MockLLM = mock_openai_like_mod.OpenAILike
        mock_llm_instance = AsyncMock()
        mock_llm_instance.achat.return_value = mock_response
        MockLLM.return_value = mock_llm_instance

        MockChatMsg = mock_core_llms_mod.ChatMessage

        with patch.dict(sys.modules, {
            "llama_index.llms.openai_like": mock_openai_like_mod,
            "llama_index.core.llms": mock_core_llms_mod,
        }):
            result = await handler.call_llm("system prompt", "user content")

        # 验证 LLM 构建参数
        MockLLM.assert_called_once_with(
            api_base="http://test.api",
            api_key="test-key",
            model="test-model",
            max_tokens=2048,
            temperature=0.5,
            is_chat_model=True,
        )
        # 验证消息构建
        assert MockChatMsg.call_count == 2
        # 验证消息发送
        mock_llm_instance.achat.assert_called_once()
        assert result == "LLM result"


# ========== 具体处理器测试 ==========


class TestMeetingNotesHandler:
    @pytest.mark.asyncio
    async def test_process_calls_llm_with_prompt(self):
        """验证 MeetingNotesHandler 使用正确的提示词调用 LLM"""
        from app.services.structuring.meeting_notes import SYSTEM_PROMPT, MeetingNotesHandler

        mock_config = MagicMock()
        handler = MeetingNotesHandler(mock_config)

        handler.call_llm = AsyncMock(return_value="# 会议纪要\n\n## 参会人\n- 张三")
        result = await handler.process("原始会议内容")

        handler.call_llm.assert_called_once_with(SYSTEM_PROMPT, "原始会议内容")
        assert result.content == "# 会议纪要\n\n## 参会人\n- 张三"
        assert result.prompt_used == SYSTEM_PROMPT


class TestPartnerProfileHandler:
    @pytest.mark.asyncio
    async def test_process_calls_llm_with_prompt(self):
        """验证 PartnerProfileHandler 使用正确的提示词调用 LLM"""
        from app.services.structuring.partner_profile import SYSTEM_PROMPT, PartnerProfileHandler

        mock_config = MagicMock()
        handler = PartnerProfileHandler(mock_config)

        handler.call_llm = AsyncMock(return_value="# 合作伙伴画像\n\n## 基本信息")
        result = await handler.process("合作伙伴信息")

        handler.call_llm.assert_called_once_with(SYSTEM_PROMPT, "合作伙伴信息")
        assert result.content == "# 合作伙伴画像\n\n## 基本信息"
        assert result.prompt_used == SYSTEM_PROMPT
