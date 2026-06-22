"""文档管线单元测试

测试范围:
- extract: 调用 run_extraction → 回写 content/source_meta → PENDING_REVIEW
- extract: 提取异常时落到 FAILED 状态
- vectorize: 非分页文档优先使用切片产物，否则回退原始内容
- vectorize: 入库失败设置 FAILED
- publish_to_feishu: 成功 / 失败状态流
- handle_bot_message: 完整消息处理流程
"""

from unittest.mock import AsyncMock, MagicMock, patch

import pytest


MODULE = "app.services.document_pipeline"


def _make_doc(**overrides):
    """构建 mock Document 对象"""
    doc = MagicMock()
    doc.id = overrides.get("id", 1)
    doc.title = overrides.get("title", "测试文档")
    doc.content = overrides.get("content", "")
    doc.source_type = overrides.get("source_type", "feishu_doc")
    doc.source_meta = overrides.get("source_meta", {})
    doc.status = overrides.get("status", "pending_extract")
    doc.error_message = None
    doc.doc_type_id = overrides.get("doc_type_id", 1)
    doc.doc_type_code = overrides.get("doc_type_code", "meeting_notes")
    doc.knowledge_base_id = overrides.get("knowledge_base_id", 1)
    doc.save = AsyncMock()
    return doc


# ========== process_document ==========


class TestProcessDocument:
    @pytest.mark.asyncio
    async def test_extract_success_sets_pending_review(self):
        """提取成功: 写回 content + source_meta → 状态 pending_review"""
        from app.services.document_pipeline import DocumentPipeline
        from app.services.extraction import ExtractionResult

        pipeline = DocumentPipeline()
        doc = _make_doc(source_meta={"existing": "v"})

        extract_result = ExtractionResult(
            content="提取后的全文",
            pages=[],
            source_meta_patch={"filename": "a.docx", "file_type": "docx"},
        )

        with patch(f"{MODULE}.Document") as MockDoc, \
             patch(f"{MODULE}.run_extraction", AsyncMock(return_value=extract_result)) as mock_run:
            MockDoc.get = AsyncMock(return_value=doc)

            await pipeline.extract(1)

        mock_run.assert_awaited_once_with(doc)
        assert doc.content == "提取后的全文"
        # source_meta 应做合并而非覆盖
        assert doc.source_meta == {"existing": "v", "filename": "a.docx", "file_type": "docx"}
        # 最终状态：pending_review
        assert doc.status == "pending_review"
        assert doc.save.await_count >= 2

    @pytest.mark.asyncio
    async def test_extract_failure_sets_failed(self):
        """提取异常: 状态置为 failed 且记录 error_message"""
        from app.services.document_pipeline import DocumentPipeline

        pipeline = DocumentPipeline()
        doc = _make_doc()

        with patch(f"{MODULE}.Document") as MockDoc, \
             patch(f"{MODULE}.run_extraction", AsyncMock(side_effect=RuntimeError("解析失败"))):
            MockDoc.get = AsyncMock(return_value=doc)

            await pipeline.extract(1)

        assert doc.status == "failed"
        assert "解析失败" in doc.error_message


# ========== vectorize_document ==========


class TestVectorizeDocument:
    @pytest.mark.asyncio
    async def test_uses_sliced_content_when_available(self):
        """非分页非合同文档：优先使用切片产物入库"""
        from app.services.document_pipeline import DocumentPipeline

        pipeline = DocumentPipeline()
        # doc_type_code 不属于 contract 也不在分页类型集合中 → 走 else 分支
        doc = _make_doc(content="原始内容", doc_type_code="__non_paged_non_contract__")

        slicing = MagicMock()
        slicing.sliced_content = "切片后的内容"

        kb = MagicMock()

        with patch(f"{MODULE}.Document") as MockDoc, \
             patch(f"{MODULE}.SlicingResult") as MockSR, \
             patch(f"{MODULE}.KnowledgeBase") as MockKB, \
             patch(f"{MODULE}.DocumentTypeCode") as MockDTC, \
             patch(f"{MODULE}.rag_service") as mock_rag:

            MockDoc.get = AsyncMock(return_value=doc)
            MockSR.filter.return_value.first = AsyncMock(return_value=slicing)
            MockKB.get = AsyncMock(return_value=kb)

            # 让分支判断都走到 else
            MockDTC.CONTRACT = "contract"
            MockDTC.is_paged_type = MagicMock(return_value=False)

            mock_rag.ingest_document = AsyncMock()

            await pipeline.vectorize(1)

        call_kwargs = mock_rag.ingest_document.call_args.kwargs
        assert call_kwargs["content"] == "切片后的内容"
        assert doc.status == "completed"

    @pytest.mark.asyncio
    async def test_falls_back_to_doc_content_without_slicing(self):
        """无切片产物时使用 doc.content"""
        from app.services.document_pipeline import DocumentPipeline

        pipeline = DocumentPipeline()
        doc = _make_doc(content="原始内容", doc_type_code="__non_paged_non_contract__")

        with patch(f"{MODULE}.Document") as MockDoc, \
             patch(f"{MODULE}.SlicingResult") as MockSR, \
             patch(f"{MODULE}.KnowledgeBase") as MockKB, \
             patch(f"{MODULE}.DocumentTypeCode") as MockDTC, \
             patch(f"{MODULE}.rag_service") as mock_rag:

            MockDoc.get = AsyncMock(return_value=doc)
            MockSR.filter.return_value.first = AsyncMock(return_value=None)
            MockKB.get = AsyncMock(return_value=MagicMock())
            MockDTC.CONTRACT = "contract"
            MockDTC.is_paged_type = MagicMock(return_value=False)
            mock_rag.ingest_document = AsyncMock()

            await pipeline.vectorize(1)

        call_kwargs = mock_rag.ingest_document.call_args.kwargs
        assert call_kwargs["content"] == "原始内容"

    @pytest.mark.asyncio
    async def test_error_sets_failed_status(self):
        """入库失败时状态设为 failed"""
        from app.services.document_pipeline import DocumentPipeline

        pipeline = DocumentPipeline()
        doc = _make_doc(content="原始内容", doc_type_code="__non_paged_non_contract__")

        with patch(f"{MODULE}.Document") as MockDoc, \
             patch(f"{MODULE}.SlicingResult") as MockSR, \
             patch(f"{MODULE}.KnowledgeBase") as MockKB, \
             patch(f"{MODULE}.DocumentTypeCode") as MockDTC, \
             patch(f"{MODULE}.rag_service") as mock_rag:

            MockDoc.get = AsyncMock(return_value=doc)
            MockSR.filter.return_value.first = AsyncMock(return_value=None)
            MockKB.get = AsyncMock(return_value=MagicMock())
            MockDTC.CONTRACT = "contract"
            MockDTC.is_paged_type = MagicMock(return_value=False)
            mock_rag.ingest_document = AsyncMock(side_effect=Exception("入库失败"))

            await pipeline.vectorize(1)

        assert doc.status == "failed"
        assert "入库失败" in doc.error_message


# ========== publish_to_feishu ==========


class TestPublishToFeishu:
    @pytest.mark.asyncio
    async def test_publish_success(self):
        """发布成功: SlicingResult.feishu_publish_status 应为 published"""
        from app.services.document_pipeline import DocumentPipeline

        pipeline = DocumentPipeline()

        sr = MagicMock()
        sr.id = 1
        sr.document_id = 10
        sr.sliced_content = "切片内容"
        sr.feishu_publish_status = None
        sr.feishu_publish_url = None
        sr.save = AsyncMock()

        doc = MagicMock()
        doc.title = "测试文档"

        mock_bot = MagicMock()
        mock_bot.app_id = "app1"
        mock_bot.app_secret = "secret1"

        with patch(f"{MODULE}.SlicingResult") as MockSR, \
             patch(f"{MODULE}.Document") as MockDoc, \
             patch(f"{MODULE}.feishu_bot_controller") as mock_bot_ctrl, \
             patch(f"{MODULE}.feishu_service") as mock_feishu, \
             patch(f"{MODULE}.settings") as mock_settings:

            MockSR.get = AsyncMock(return_value=sr)
            MockDoc.get = AsyncMock(return_value=doc)
            mock_bot_ctrl.model.filter.return_value.first = AsyncMock(return_value=mock_bot)
            mock_feishu.get_tenant_access_token = AsyncMock(return_value="t-token")
            mock_feishu.create_doc_in_folder = AsyncMock(return_value="https://feishu.cn/docx/abc")
            mock_settings.FEISHU_STRUCTURED_FOLDER_TOKEN = "folder1"

            await pipeline.publish_to_feishu(1)

        assert sr.feishu_publish_status == "published"
        assert sr.feishu_publish_url == "https://feishu.cn/docx/abc"
        # publish_to_feishu 内部应使用 sliced_content 作为正文
        published_kwargs = mock_feishu.create_doc_in_folder.call_args.kwargs
        assert published_kwargs["content"] == "切片内容"

    @pytest.mark.asyncio
    async def test_publish_failure(self):
        """发布失败: SlicingResult.feishu_publish_status 设为 failed"""
        from app.services.document_pipeline import DocumentPipeline

        pipeline = DocumentPipeline()

        sr = MagicMock()
        sr.id = 1
        sr.document_id = 10
        sr.feishu_publish_status = None
        sr.save = AsyncMock()

        doc = MagicMock()
        doc.title = "测试"

        with patch(f"{MODULE}.SlicingResult") as MockSR, \
             patch(f"{MODULE}.Document") as MockDoc, \
             patch(f"{MODULE}.feishu_bot_controller") as mock_bot_ctrl:

            MockSR.get = AsyncMock(return_value=sr)
            MockDoc.get = AsyncMock(return_value=doc)
            mock_bot_ctrl.model.filter.return_value.first = AsyncMock(return_value=None)

            await pipeline.publish_to_feishu(1)

        assert sr.feishu_publish_status == "failed"


# ========== handle_bot_message ==========


class TestHandleBotMessage:
    @pytest.mark.asyncio
    async def test_no_knowledge_bases(self):
        """Agent 未关联知识库时返回提示"""
        from app.services.bot_service import BotService

        bot_svc = BotService()

        mock_bot = MagicMock()
        mock_bot.agent_id = 1
        mock_agent = MagicMock()
        mock_agent.id = 1
        mock_agent.knowledge_bases = MagicMock()
        mock_agent.knowledge_bases.all = AsyncMock(return_value=[])

        with patch("app.services.bot_service.feishu_bot_controller") as mock_bot_ctrl, \
             patch("app.services.bot_service.Agent") as MockAgent:

            mock_bot_ctrl.get = AsyncMock(return_value=mock_bot)
            MockAgent.get = AsyncMock(return_value=mock_agent)

            result = await bot_svc.handle_message(1, "ou_123", "chat1", "你好")

        assert "未关联任何知识库" in result["answer"]
        assert result["sources"] == []

    @pytest.mark.asyncio
    async def test_full_flow_existing_user(self):
        """完整消息处理流: 已有用户 → 获取对话 → RAG 问答 → 保存消息"""
        from app.services.bot_service import BotService

        bot_svc = BotService()

        mock_bot = MagicMock()
        mock_bot.agent_id = 1
        mock_agent = MagicMock()
        mock_agent.id = 1
        mock_agent.chat_model_id = 5
        mock_agent.system_prompt = "你是AI助手"
        mock_agent.max_history_turns = 5
        mock_agent.knowledge_bases = MagicMock()
        mock_kb = MagicMock()
        mock_agent.knowledge_bases.all = AsyncMock(return_value=[mock_kb])

        mock_user = MagicMock()
        mock_user.id = 10

        mock_conv = MagicMock()
        mock_conv.id = 100
        mock_conv.message_count = 0
        mock_conv.last_active_at = None
        mock_conv.save = AsyncMock()

        mock_chat_model = MagicMock()
        mock_chat_model.id = 5

        rag_result = {"answer": "AI 的回答", "sources": [{"score": 0.9, "text_preview": "src"}]}

        with patch("app.services.bot_service.feishu_bot_controller") as mock_bot_ctrl, \
             patch("app.services.bot_service.Agent") as MockAgent, \
             patch("app.services.bot_service.User") as MockUser, \
             patch("app.services.bot_service.conversation_controller") as mock_conv_ctrl, \
             patch("app.services.bot_service.LLMProviderConfig") as MockLLMConfig, \
             patch("app.services.bot_service.rag_service") as mock_rag, \
             patch("app.services.bot_service.ChatMessage") as MockChatMsg:

            mock_bot_ctrl.get = AsyncMock(return_value=mock_bot)
            MockAgent.get = AsyncMock(return_value=mock_agent)
            MockUser.filter.return_value.first = AsyncMock(return_value=mock_user)
            mock_conv_ctrl.get_or_create = AsyncMock(return_value=mock_conv)
            mock_conv_ctrl.get_messages = AsyncMock(return_value=[])
            MockLLMConfig.get = AsyncMock(return_value=mock_chat_model)
            mock_rag.chat = AsyncMock(return_value=rag_result)
            MockChatMsg.create = AsyncMock()

            result = await bot_svc.handle_message(1, "ou_exist", "chat1", "帮我查资料")

        assert result["answer"] == "AI 的回答"
        mock_rag.chat.assert_called_once()
        # user + assistant
        assert MockChatMsg.create.call_count == 2
        assert mock_conv.message_count == 2
