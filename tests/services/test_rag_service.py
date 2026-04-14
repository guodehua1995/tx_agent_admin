"""RAG 服务单元测试

测试范围:
- 向量存储初始化
- LLM / Embedding 模型构建
- 节点解析器构建（3 种模式）
- 文档入库
- 文档 / 知识库向量删除
- RAG 问答 query
- 多轮对话 chat
- 模型连接测试
"""

import sys
from unittest.mock import AsyncMock, MagicMock, patch

import pytest


def _mock_llama_modules():
    """预构建 LlamaIndex 的 mock 模块，返回 (modules_dict, refs_dict)。

    refs_dict 包含常用的 mock class 引用，方便断言。
    """
    mods = {}
    refs = {}

    # llama_index.vector_stores.postgres
    m = MagicMock()
    refs["PGVectorStore"] = m.PGVectorStore
    mods["llama_index.vector_stores.postgres"] = m

    # llama_index.llms.openai_like
    m = MagicMock()
    refs["OpenAILike"] = m.OpenAILike
    mods["llama_index.llms.openai_like"] = m

    # llama_index.embeddings.openai
    m = MagicMock()
    refs["OpenAIEmbedding"] = m.OpenAIEmbedding
    mods["llama_index.embeddings.openai"] = m

    # llama_index.core.node_parser
    m = MagicMock()
    refs["SentenceSplitter"] = m.SentenceSplitter
    refs["MarkdownNodeParser"] = m.MarkdownNodeParser
    refs["HierarchicalNodeParser"] = m.HierarchicalNodeParser
    mods["llama_index.core.node_parser"] = m

    # llama_index.core.ingestion
    m = MagicMock()
    refs["IngestionPipeline"] = m.IngestionPipeline
    mods["llama_index.core.ingestion"] = m

    # llama_index.core.schema
    m = MagicMock()
    refs["LlamaDocument"] = m.Document
    mods["llama_index.core.schema"] = m

    # llama_index.core
    m = MagicMock()
    refs["VectorStoreIndex"] = m.VectorStoreIndex
    mods["llama_index.core"] = m

    # llama_index.core.vector_stores
    m = MagicMock()
    refs["ExactMatchFilter"] = m.ExactMatchFilter
    refs["MetadataFilters"] = m.MetadataFilters
    mods["llama_index.core.vector_stores"] = m

    # llama_index.core.llms
    m = MagicMock()
    refs["LlamaChatMessage"] = m.ChatMessage
    mods["llama_index.core.llms"] = m

    # llama_index.core.chat_engine
    m = MagicMock()
    refs["CondensePlusContextChatEngine"] = m.CondensePlusContextChatEngine
    mods["llama_index.core.chat_engine"] = m

    return mods, refs


def _make_kb(**overrides):
    """构建一个 mock KnowledgeBase 对象"""
    kb = MagicMock()
    kb.id = overrides.get("id", 1)
    kb.name = overrides.get("name", "test_kb")
    kb.chunk_mode = overrides.get("chunk_mode", "sentence")
    kb.chunk_size = overrides.get("chunk_size", 512)
    kb.chunk_overlap = overrides.get("chunk_overlap", 50)
    kb.embedding_model_id = overrides.get("embedding_model_id", 10)
    kb.retrieval_mode = overrides.get("retrieval_mode", "vector")
    kb.similarity_top_k = overrides.get("similarity_top_k", 5)
    kb.similarity_threshold = overrides.get("similarity_threshold", 0.7)
    return kb


def _make_llm_config(**overrides):
    """构建一个 mock LLMProviderConfig 对象"""
    config = MagicMock()
    config.api_base_url = overrides.get("api_base_url", "http://llm.test")
    config.api_key = overrides.get("api_key", "key123")
    config.model_name = overrides.get("model_name", "test-model")
    config.max_tokens = overrides.get("max_tokens", 2048)
    config.extra_config = overrides.get("extra_config", {})
    config.is_embedding = overrides.get("is_embedding", False)
    return config


# ========== 初始化 ==========


class TestRAGServiceInit:
    def test_vector_store_none_on_init(self):
        from app.services.rag_service import RAGService

        svc = RAGService()
        assert svc._vector_store is None

    @pytest.mark.asyncio
    async def test_init_vector_store(self):
        from app.services.rag_service import RAGService

        svc = RAGService()
        mods, refs = _mock_llama_modules()

        with patch.dict(sys.modules, mods):
            await svc.init_vector_store()

        refs["PGVectorStore"].from_params.assert_called_once()
        assert svc._vector_store is not None


# ========== _build_llm ==========


class TestBuildLLM:
    def test_builds_with_correct_params(self):
        from app.services.rag_service import RAGService

        svc = RAGService()
        config = _make_llm_config(extra_config={"temperature": 0.5})

        mods, refs = _mock_llama_modules()
        with patch.dict(sys.modules, mods):
            svc._build_llm(config)

        refs["OpenAILike"].assert_called_once_with(
            api_base="http://llm.test",
            api_key="key123",
            model="test-model",
            max_tokens=2048,
            temperature=0.5,
            is_chat_model=True,
        )

    def test_default_temperature(self):
        from app.services.rag_service import RAGService

        svc = RAGService()
        config = _make_llm_config(extra_config={})

        mods, refs = _mock_llama_modules()
        with patch.dict(sys.modules, mods):
            svc._build_llm(config)

        call_kwargs = refs["OpenAILike"].call_args[1]
        assert call_kwargs["temperature"] == 0.7


# ========== _build_embed_model ==========


class TestBuildEmbedModel:
    def test_builds_with_correct_params(self):
        from app.services.rag_service import RAGService

        svc = RAGService()
        config = _make_llm_config(model_name="embed-model")

        mods, refs = _mock_llama_modules()
        with patch.dict(sys.modules, mods):
            svc._build_embed_model(config)

        refs["OpenAIEmbedding"].assert_called_once_with(
            api_base="http://llm.test",
            api_key="key123",
            model_name="embed-model",
            embed_batch_size=10,
        )


# ========== _build_node_parser ==========


class TestBuildNodeParser:
    def test_sentence_mode(self):
        from app.services.rag_service import RAGService

        svc = RAGService()
        kb = _make_kb(chunk_mode="sentence", chunk_size=256, chunk_overlap=20)

        mods, refs = _mock_llama_modules()
        with patch.dict(sys.modules, mods):
            svc._build_node_parser(kb)

        refs["SentenceSplitter"].assert_called_once_with(chunk_size=256, chunk_overlap=20)

    def test_markdown_mode(self):
        from app.services.rag_service import RAGService

        svc = RAGService()
        kb = _make_kb(chunk_mode="markdown")

        mods, refs = _mock_llama_modules()
        with patch.dict(sys.modules, mods):
            svc._build_node_parser(kb)

        refs["MarkdownNodeParser"].assert_called_once()

    def test_hierarchical_mode(self):
        from app.services.rag_service import RAGService

        svc = RAGService()
        kb = _make_kb(chunk_mode="hierarchical")

        mods, refs = _mock_llama_modules()
        with patch.dict(sys.modules, mods):
            svc._build_node_parser(kb)

        refs["HierarchicalNodeParser"].from_defaults.assert_called_once_with(
            chunk_sizes=[1024, 512, 256]
        )


# ========== ingest_document ==========


class TestIngestDocument:
    @pytest.mark.asyncio
    async def test_ingest_calls_pipeline(self):
        from app.services.rag_service import RAGService

        svc = RAGService()
        svc._vector_store = MagicMock()

        kb = _make_kb()
        config = _make_llm_config()

        mods, refs = _mock_llama_modules()
        mock_pipeline_instance = AsyncMock()
        refs["IngestionPipeline"].return_value = mock_pipeline_instance

        with patch.dict(sys.modules, mods), \
             patch("app.services.rag_service.LLMProviderConfig") as MockLLMConfig:
            MockLLMConfig.get = AsyncMock(return_value=config)
            svc._build_embed_model = MagicMock(return_value="embed_model")
            svc._build_node_parser = MagicMock(return_value="node_parser")

            await svc.ingest_document("doc1", "content text", kb, {"title": "Test"})

        mock_pipeline_instance.arun.assert_called_once()
        refs["LlamaDocument"].assert_called_once()


# ========== delete_document ==========


class TestDeleteDocument:
    @pytest.mark.asyncio
    async def test_deletes_when_store_exists(self):
        from app.services.rag_service import RAGService

        svc = RAGService()
        svc._vector_store = AsyncMock()

        await svc.delete_document("doc1")

        svc._vector_store.adelete.assert_called_once_with("doc1")

    @pytest.mark.asyncio
    async def test_noop_when_store_none(self):
        from app.services.rag_service import RAGService

        svc = RAGService()
        svc._vector_store = None

        # 不应抛异常
        await svc.delete_document("doc1")


# ========== delete_by_knowledge_base ==========


class TestDeleteByKnowledgeBase:
    @pytest.mark.asyncio
    async def test_deletes_with_filter(self):
        from app.services.rag_service import RAGService

        svc = RAGService()
        svc._vector_store = AsyncMock()

        mods, refs = _mock_llama_modules()
        with patch.dict(sys.modules, mods):
            await svc.delete_by_knowledge_base(42)

        svc._vector_store.adelete.assert_called_once()
        refs["MetadataFilters"].assert_called_once()

    @pytest.mark.asyncio
    async def test_noop_when_store_none(self):
        from app.services.rag_service import RAGService

        svc = RAGService()
        svc._vector_store = None

        mods, _ = _mock_llama_modules()
        with patch.dict(sys.modules, mods):
            await svc.delete_by_knowledge_base(42)


# ========== query ==========


class TestQuery:
    @pytest.mark.asyncio
    async def test_query_returns_answer_and_sources(self):
        from app.services.rag_service import RAGService

        svc = RAGService()
        svc._vector_store = MagicMock()

        kb = _make_kb(similarity_top_k=3, similarity_threshold=0.5)
        chat_config = _make_llm_config()

        # mock source nodes
        node1 = MagicMock()
        node1.score = 0.9
        node1.text = "relevant content"
        node1.metadata = {"title": "doc1"}

        node2 = MagicMock()
        node2.score = 0.3  # 低于阈值
        node2.text = "irrelevant"
        node2.metadata = {"title": "doc2"}

        mock_response = MagicMock()
        mock_response.__str__ = lambda self: "AI answer"
        mock_response.source_nodes = [node1, node2]

        mods, refs = _mock_llama_modules()
        mock_query_engine = AsyncMock()
        mock_query_engine.aquery.return_value = mock_response

        mock_index = MagicMock()
        mock_index.as_query_engine.return_value = mock_query_engine
        refs["VectorStoreIndex"].from_vector_store.return_value = mock_index

        embed_config = _make_llm_config()

        with patch.dict(sys.modules, mods), \
             patch("app.services.rag_service.LLMProviderConfig") as MockLLMConfig:
            MockLLMConfig.get = AsyncMock(return_value=embed_config)
            svc._build_llm = MagicMock(return_value="llm")
            svc._build_embed_model = MagicMock(return_value="embed")

            result = await svc.query("问题?", [kb], chat_config)

        assert result["answer"] == "AI answer"
        # 只有 score >= 0.5 的被保留
        assert len(result["sources"]) == 1
        assert result["sources"][0]["score"] == 0.9


# ========== chat ==========


class TestChat:
    @pytest.mark.asyncio
    async def test_chat_with_history(self):
        from app.services.rag_service import RAGService

        svc = RAGService()
        svc._vector_store = MagicMock()

        kb = _make_kb(similarity_top_k=3, similarity_threshold=0.5)
        chat_config = _make_llm_config()

        node1 = MagicMock()
        node1.score = 0.8
        node1.text = "source content"
        node1.metadata = {"title": "src"}

        mock_response = MagicMock()
        mock_response.__str__ = lambda self: "chat answer"
        mock_response.source_nodes = [node1]

        mods, refs = _mock_llama_modules()

        mock_chat_engine = AsyncMock()
        mock_chat_engine.achat.return_value = mock_response
        refs["CondensePlusContextChatEngine"].from_defaults.return_value = mock_chat_engine

        mock_index = MagicMock()
        mock_retriever = MagicMock()
        mock_index.as_retriever.return_value = mock_retriever
        refs["VectorStoreIndex"].from_vector_store.return_value = mock_index

        embed_config = _make_llm_config()
        history = [
            {"role": "user", "content": "hi"},
            {"role": "assistant", "content": "hello"},
        ]

        with patch.dict(sys.modules, mods), \
             patch("app.services.rag_service.LLMProviderConfig") as MockLLMConfig:
            MockLLMConfig.get = AsyncMock(return_value=embed_config)
            svc._build_llm = MagicMock(return_value="llm")
            svc._build_embed_model = MagicMock(return_value="embed")

            result = await svc.chat("new question", history, [kb], chat_config, "sys prompt")

        assert result["answer"] == "chat answer"
        assert len(result["sources"]) == 1
        mock_chat_engine.achat.assert_called_once()
        refs["CondensePlusContextChatEngine"].from_defaults.assert_called_once()


# ========== test_model_connection ==========


class TestModelConnection:
    @pytest.mark.asyncio
    async def test_llm_connection_success(self):
        from app.services.rag_service import RAGService

        svc = RAGService()
        config = _make_llm_config(is_embedding=False)

        mock_llm = AsyncMock()
        svc._build_llm = MagicMock(return_value=mock_llm)

        result = await svc.test_model_connection(config)

        assert result is True
        mock_llm.acomplete.assert_called_once_with("Hello")

    @pytest.mark.asyncio
    async def test_embedding_connection_success(self):
        from app.services.rag_service import RAGService

        svc = RAGService()
        config = _make_llm_config(is_embedding=True)

        mock_embed = AsyncMock()
        svc._build_embed_model = MagicMock(return_value=mock_embed)

        result = await svc.test_model_connection(config)

        assert result is True
        mock_embed.aget_text_embedding.assert_called_once_with("test")

    @pytest.mark.asyncio
    async def test_connection_failure(self):
        from app.services.rag_service import RAGService

        svc = RAGService()
        config = _make_llm_config(is_embedding=False)

        mock_llm = AsyncMock()
        mock_llm.acomplete.side_effect = Exception("connection refused")
        svc._build_llm = MagicMock(return_value=mock_llm)

        result = await svc.test_model_connection(config)

        assert result is False
