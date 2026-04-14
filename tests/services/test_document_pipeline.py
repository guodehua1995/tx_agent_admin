"""文档管线单元测试

测试范围:
- process_document: 三种来源类型（飞书、文件、URL）
- process_document: 含结构化流程
- process_document: 错误处理
- vectorize_document: 审核内容优先 / 结构化内容 / 原始内容
- publish_to_feishu: 发布成功 / 失败处理
- handle_bot_message: 完整消息处理流程
"""

import sys
from unittest.mock import AsyncMock, MagicMock, patch, mock_open

import pytest


MODULE = "app.services.document_pipeline"


def _make_doc(**overrides):
    """构建 mock Document 对象"""
    doc = AsyncMock()
    doc.id = overrides.get("id", 1)
    doc.title = overrides.get("title", "测试文档")
    doc.content = overrides.get("content", "")
    doc.source_type = overrides.get("source_type", "feishu_doc")
    doc.source_meta = overrides.get("source_meta", {})
    doc.status = overrides.get("status", "pending_fetch")
    doc.error_message = None
    doc.doc_type_id = overrides.get("doc_type_id", 1)
    doc.knowledge_base_id = overrides.get("knowledge_base_id", 1)
    doc.save = AsyncMock()
    return doc


# ========== process_document ==========


class TestProcessDocument:
    @pytest.mark.asyncio
    async def test_feishu_source_success(self):
        """飞书文档来源: 拉取内容 → 结构化 → 待审核"""
        from app.services.document_pipeline import DocumentPipeline

        pipeline = DocumentPipeline()
        doc = _make_doc(
            source_type="feishu_doc",
            source_meta={"feishu_url": "https://abc.feishu.cn/docx/Token123"},
        )
        doc_type = MagicMock()
        doc_type.needs_structuring = False

        with patch(f"{MODULE}.Document") as MockDoc, \
             patch(f"{MODULE}.feishu_service") as mock_feishu, \
             patch(f"{MODULE}.document_type_controller") as mock_dt_ctrl, \
             patch(f"{MODULE}.feishu_bot_controller") as mock_bot_ctrl:

            MockDoc.get = AsyncMock(return_value=doc)
            mock_feishu.parse_feishu_url.return_value = ("Token123", "docx")

            # 模拟活跃的飞书机器人配置
            mock_bot = MagicMock()
            mock_bot.app_id = "app1"
            mock_bot.app_secret = "secret1"
            mock_bot_ctrl.model.filter.return_value.first = AsyncMock(return_value=mock_bot)

            mock_feishu.get_tenant_access_token = AsyncMock(return_value="t-token")
            mock_feishu.fetch_document_content = AsyncMock(return_value="飞书文档内容")

            mock_dt_ctrl.get = AsyncMock(return_value=doc_type)

            await pipeline.process_document(1)

        # 文档内容应被设置
        assert doc.content == "飞书文档内容"
        # 最终状态应为 pending_review
        assert doc.status == "pending_review"
        assert doc.save.call_count >= 2

    @pytest.mark.asyncio
    async def test_file_upload_source(self):
        """文件上传来源: 读取文件 → 待审核"""
        from app.services.document_pipeline import DocumentPipeline

        pipeline = DocumentPipeline()
        doc = _make_doc(
            source_type="file_upload",
            source_meta={"file_path": "/tmp/test.txt"},
        )
        doc_type = MagicMock()
        doc_type.needs_structuring = False

        with patch(f"{MODULE}.Document") as MockDoc, \
             patch(f"{MODULE}.document_type_controller") as mock_dt_ctrl, \
             patch("builtins.open", mock_open(read_data="文件内容")):

            MockDoc.get = AsyncMock(return_value=doc)
            mock_dt_ctrl.get = AsyncMock(return_value=doc_type)

            await pipeline.process_document(1)

        assert doc.content == "文件内容"
        assert doc.status == "pending_review"

    @pytest.mark.asyncio
    async def test_web_url_source(self):
        """URL 来源: 抓取网页 → 待审核"""
        from app.services.document_pipeline import DocumentPipeline

        pipeline = DocumentPipeline()
        doc = _make_doc(
            source_type="web_url",
            source_meta={"url": "https://example.com"},
        )
        doc_type = MagicMock()
        doc_type.needs_structuring = False

        mock_resp = MagicMock()
        mock_resp.text = "<html>网页内容</html>"
        mock_client = AsyncMock()
        mock_client.get = AsyncMock(return_value=mock_resp)
        mock_ctx = AsyncMock()
        mock_ctx.__aenter__.return_value = mock_client

        with patch(f"{MODULE}.Document") as MockDoc, \
             patch(f"{MODULE}.document_type_controller") as mock_dt_ctrl, \
             patch(f"{MODULE}.httpx", create=True):

            MockDoc.get = AsyncMock(return_value=doc)
            mock_dt_ctrl.get = AsyncMock(return_value=doc_type)

            # httpx 在 _fetch_web_content 内部是懒导入的
            mock_httpx_mod = MagicMock()
            mock_httpx_mod.AsyncClient.return_value = mock_ctx
            with patch.dict(sys.modules, {"httpx": mock_httpx_mod}):
                await pipeline.process_document(1)

        assert doc.content == "<html>网页内容</html>"
        assert doc.status == "pending_review"

    @pytest.mark.asyncio
    async def test_with_structuring(self):
        """文档需要结构化: 获取内容 → 结构化 → 待审核"""
        from app.services.document_pipeline import DocumentPipeline

        pipeline = DocumentPipeline()
        doc = _make_doc(
            source_type="file_upload",
            source_meta={"file_path": "/tmp/test.txt"},
        )
        doc_type = MagicMock()
        doc_type.needs_structuring = True
        doc_type.code = "meeting_notes"

        mock_structuring_result = MagicMock()
        mock_structuring_result.content = "结构化后的内容"
        mock_structuring_result.prompt_used = "prompt"
        mock_structuring_result.token_usage = {}

        chat_model = MagicMock()
        chat_model.id = 5

        with patch(f"{MODULE}.Document") as MockDoc, \
             patch(f"{MODULE}.document_type_controller") as mock_dt_ctrl, \
             patch(f"{MODULE}.ai_config_controller") as mock_ai_ctrl, \
             patch(f"{MODULE}.run_structuring") as mock_run_struct, \
             patch(f"{MODULE}.StructuredResult") as MockSR, \
             patch("builtins.open", mock_open(read_data="原始内容")):

            MockDoc.get = AsyncMock(return_value=doc)
            mock_dt_ctrl.get = AsyncMock(return_value=doc_type)
            mock_ai_ctrl.get_active_chat_models = AsyncMock(return_value=[chat_model])
            mock_run_struct.return_value = mock_structuring_result
            MockSR.create = AsyncMock()

            await pipeline.process_document(1)

        mock_run_struct.assert_called_once_with("meeting_notes", "原始内容", chat_model)
        MockSR.create.assert_called_once()
        assert doc.status == "pending_review"

    @pytest.mark.asyncio
    async def test_error_sets_failed_status(self):
        """处理失败时文档状态应设为 failed"""
        from app.services.document_pipeline import DocumentPipeline

        pipeline = DocumentPipeline()
        doc = _make_doc(source_type="file_upload", source_meta={"file_path": ""})

        with patch(f"{MODULE}.Document") as MockDoc:
            MockDoc.get = AsyncMock(return_value=doc)

            await pipeline.process_document(1)

        assert doc.status == "failed"
        assert doc.error_message is not None


# ========== vectorize_document ==========


class TestVectorizeDocument:
    @pytest.mark.asyncio
    async def test_uses_edited_review_content(self):
        """优先使用审核编辑后的内容"""
        from app.services.document_pipeline import DocumentPipeline

        pipeline = DocumentPipeline()
        doc = _make_doc(content="原始内容")
        review = MagicMock()
        review.edited_content = "审核编辑后的内容"

        kb = MagicMock()
        kb.id = 1

        with patch(f"{MODULE}.Document") as MockDoc, \
             patch(f"{MODULE}.review_controller") as mock_review_ctrl, \
             patch(f"{MODULE}.KnowledgeBase") as MockKB, \
             patch(f"{MODULE}.rag_service") as mock_rag:

            MockDoc.get = AsyncMock(return_value=doc)
            mock_review_ctrl.get_by_document = AsyncMock(return_value=[review])
            MockKB.get = AsyncMock(return_value=kb)
            mock_rag.ingest_document = AsyncMock()

            await pipeline.vectorize_document(1)

        # 验证使用的是审核编辑内容
        call_kwargs = mock_rag.ingest_document.call_args[1]
        assert call_kwargs["content"] == "审核编辑后的内容"
        assert doc.status == "completed"

    @pytest.mark.asyncio
    async def test_uses_structured_content(self):
        """无编辑内容时使用结构化内容"""
        from app.services.document_pipeline import DocumentPipeline

        pipeline = DocumentPipeline()
        doc = _make_doc(content="原始内容")
        review = MagicMock()
        review.edited_content = None

        structured = MagicMock()
        structured.structured_content = "结构化内容"

        kb = MagicMock()

        with patch(f"{MODULE}.Document") as MockDoc, \
             patch(f"{MODULE}.review_controller") as mock_review_ctrl, \
             patch(f"{MODULE}.StructuredResult") as MockSR, \
             patch(f"{MODULE}.KnowledgeBase") as MockKB, \
             patch(f"{MODULE}.rag_service") as mock_rag:

            MockDoc.get = AsyncMock(return_value=doc)
            mock_review_ctrl.get_by_document = AsyncMock(return_value=[review])
            MockSR.filter.return_value.first = AsyncMock(return_value=structured)
            MockKB.get = AsyncMock(return_value=kb)
            mock_rag.ingest_document = AsyncMock()

            await pipeline.vectorize_document(1)

        call_kwargs = mock_rag.ingest_document.call_args[1]
        assert call_kwargs["content"] == "结构化内容"

    @pytest.mark.asyncio
    async def test_error_sets_failed_status(self):
        """入库失败时状态设为 failed"""
        from app.services.document_pipeline import DocumentPipeline

        pipeline = DocumentPipeline()
        doc = _make_doc(content="原始内容")

        with patch(f"{MODULE}.Document") as MockDoc, \
             patch(f"{MODULE}.review_controller") as mock_review_ctrl, \
             patch(f"{MODULE}.KnowledgeBase") as MockKB, \
             patch(f"{MODULE}.rag_service") as mock_rag:

            MockDoc.get = AsyncMock(return_value=doc)
            mock_review_ctrl.get_by_document = AsyncMock(return_value=[])
            MockKB.get = AsyncMock(return_value=MagicMock())
            mock_rag.ingest_document = AsyncMock(side_effect=Exception("入库失败"))

            # StructuredResult.filter 也需要 mock
            with patch(f"{MODULE}.StructuredResult") as MockSR:
                MockSR.filter.return_value.first = AsyncMock(return_value=None)
                await pipeline.vectorize_document(1)

        assert doc.status == "failed"
        assert "入库失败" in doc.error_message


# ========== publish_to_feishu ==========


class TestPublishToFeishu:
    @pytest.mark.asyncio
    async def test_publish_success(self):
        """发布成功: 状态更新为 published"""
        from app.services.document_pipeline import DocumentPipeline

        pipeline = DocumentPipeline()

        sr = AsyncMock()
        sr.id = 1
        sr.document_id = 10
        sr.structured_content = "结构化内容"
        sr.feishu_publish_status = None
        sr.feishu_publish_url = None
        sr.save = AsyncMock()

        doc = MagicMock()
        doc.title = "测试文档"

        mock_bot = MagicMock()
        mock_bot.app_id = "app1"
        mock_bot.app_secret = "secret1"

        with patch(f"{MODULE}.StructuredResult") as MockSR, \
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

    @pytest.mark.asyncio
    async def test_publish_failure(self):
        """发布失败: 状态设为 failed"""
        from app.services.document_pipeline import DocumentPipeline

        pipeline = DocumentPipeline()

        sr = AsyncMock()
        sr.id = 1
        sr.document_id = 10
        sr.feishu_publish_status = None
        sr.save = AsyncMock()

        doc = MagicMock()
        doc.title = "测试"

        with patch(f"{MODULE}.StructuredResult") as MockSR, \
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
        from app.services.document_pipeline import DocumentPipeline

        pipeline = DocumentPipeline()

        mock_bot = MagicMock()
        mock_bot.agent_id = 1
        mock_agent = MagicMock()
        mock_agent.id = 1
        mock_agent.knowledge_bases = AsyncMock()
        mock_agent.knowledge_bases.all = AsyncMock(return_value=[])

        with patch(f"{MODULE}.feishu_bot_controller") as mock_bot_ctrl, \
             patch(f"{MODULE}.Agent") as MockAgent:

            mock_bot_ctrl.get = AsyncMock(return_value=mock_bot)
            MockAgent.get = AsyncMock(return_value=mock_agent)

            result = await pipeline.handle_bot_message(1, "ou_123", "chat1", "你好")

        assert "未关联任何知识库" in result["answer"]
        assert result["sources"] == []

    @pytest.mark.asyncio
    async def test_full_flow_existing_user(self):
        """完整消息处理流: 已有用户 → 获取对话 → RAG 问答 → 保存消息"""
        from app.services.document_pipeline import DocumentPipeline

        pipeline = DocumentPipeline()

        mock_bot = MagicMock()
        mock_bot.agent_id = 1
        mock_agent = MagicMock()
        mock_agent.id = 1
        mock_agent.chat_model_id = 5
        mock_agent.system_prompt = "你是AI助手"
        mock_agent.max_history_turns = 5
        mock_agent.knowledge_bases = AsyncMock()
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

        with patch(f"{MODULE}.feishu_bot_controller") as mock_bot_ctrl, \
             patch(f"{MODULE}.Agent") as MockAgent, \
             patch(f"{MODULE}.User") as MockUser, \
             patch(f"{MODULE}.conversation_controller") as mock_conv_ctrl, \
             patch(f"{MODULE}.LLMProviderConfig") as MockLLMConfig, \
             patch(f"{MODULE}.rag_service") as mock_rag, \
             patch(f"{MODULE}.ChatMessage") as MockChatMsg:

            mock_bot_ctrl.get = AsyncMock(return_value=mock_bot)
            MockAgent.get = AsyncMock(return_value=mock_agent)
            MockUser.filter.return_value.first = AsyncMock(return_value=mock_user)
            mock_conv_ctrl.get_or_create = AsyncMock(return_value=mock_conv)
            mock_conv_ctrl.get_messages = AsyncMock(return_value=[])
            MockLLMConfig.get = AsyncMock(return_value=mock_chat_model)
            mock_rag.chat = AsyncMock(return_value=rag_result)
            MockChatMsg.create = AsyncMock()

            result = await pipeline.handle_bot_message(1, "ou_exist", "chat1", "帮我查资料")

        assert result["answer"] == "AI 的回答"
        mock_rag.chat.assert_called_once()
        assert MockChatMsg.create.call_count == 2  # user + assistant
        assert mock_conv.message_count == 2

    @pytest.mark.asyncio
    async def test_creates_user_if_not_found(self):
        """飞书用户不存在时自动创建"""
        from app.services.document_pipeline import DocumentPipeline

        pipeline = DocumentPipeline()

        mock_bot = MagicMock()
        mock_bot.agent_id = 1
        mock_agent = MagicMock()
        mock_agent.id = 1
        mock_agent.chat_model_id = 5
        mock_agent.system_prompt = ""
        mock_agent.max_history_turns = 3
        mock_agent.knowledge_bases = AsyncMock()
        mock_kb = MagicMock()
        mock_agent.knowledge_bases.all = AsyncMock(return_value=[mock_kb])

        mock_new_user = MagicMock()
        mock_new_user.id = 99

        mock_conv = MagicMock()
        mock_conv.id = 100
        mock_conv.message_count = 0
        mock_conv.save = AsyncMock()

        with patch(f"{MODULE}.feishu_bot_controller") as mock_bot_ctrl, \
             patch(f"{MODULE}.Agent") as MockAgent, \
             patch(f"{MODULE}.User") as MockUser, \
             patch(f"{MODULE}.conversation_controller") as mock_conv_ctrl, \
             patch(f"{MODULE}.LLMProviderConfig") as MockLLMConfig, \
             patch(f"{MODULE}.rag_service") as mock_rag, \
             patch(f"{MODULE}.ChatMessage") as MockChatMsg:

            mock_bot_ctrl.get = AsyncMock(return_value=mock_bot)
            MockAgent.get = AsyncMock(return_value=mock_agent)
            MockUser.filter.return_value.first = AsyncMock(return_value=None)
            MockUser.create = AsyncMock(return_value=mock_new_user)
            mock_conv_ctrl.get_or_create = AsyncMock(return_value=mock_conv)
            mock_conv_ctrl.get_messages = AsyncMock(return_value=[])
            MockLLMConfig.get = AsyncMock(return_value=MagicMock())
            mock_rag.chat = AsyncMock(return_value={"answer": "hi", "sources": []})
            MockChatMsg.create = AsyncMock()

            await pipeline.handle_bot_message(1, "ou_newuser", "chat1", "你好")

        MockUser.create.assert_called_once()
        create_kwargs = MockUser.create.call_args[1]
        assert create_kwargs["feishu_open_id"] == "ou_newuser"
