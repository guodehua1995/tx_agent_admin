from app.log import logger
from app.models.rag import KnowledgeBase, LLMProviderConfig
from app.settings import settings


class RAGService:
    """封装 LlamaIndex，提供文档入库和问答能力"""

    def __init__(self):
        self._vector_store = None

    async def init_vector_store(self):
        """初始化 PGVectorStore（应用启动时调用一次）"""
        from llama_index.vector_stores.postgres import PGVectorStore

        self._vector_store = PGVectorStore.from_params(
            host=settings.DB_HOST,
            port=str(settings.DB_PORT),
            database=settings.DB_NAME,
            user=settings.DB_USER,
            password=settings.DB_PASSWORD,
            table_name=settings.VECTOR_STORE_TABLE_NAME,
            embed_dim=settings.DEFAULT_EMBEDDING_DIMENSION,
            hybrid_search=True,
            perform_setup=True,
        )
        logger.info(f"PGVectorStore initialized: table={settings.VECTOR_STORE_TABLE_NAME}")

    def _build_llm(self, config: LLMProviderConfig):
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
        )

    def _build_embed_model(self, config: LLMProviderConfig):
        """根据数据库配置动态构建 Embedding 模型"""
        from llama_index.embeddings.openai import OpenAIEmbedding

        return OpenAIEmbedding(
            api_base=config.api_base_url,
            api_key=config.api_key,
            model_name=config.model_name,
            embed_batch_size=10,
            dimensions=settings.DEFAULT_EMBEDDING_DIMENSION,
        )

    def _build_node_parser(self, kb: KnowledgeBase):
        """根据知识库的 chunk_mode 配置构建对应的 NodeParser"""
        from llama_index.core.node_parser import (
            HierarchicalNodeParser,
            MarkdownNodeParser,
            SentenceSplitter,
        )

        if kb.chunk_mode == "markdown":
            return MarkdownNodeParser()
        elif kb.chunk_mode == "hierarchical":
            return HierarchicalNodeParser.from_defaults(chunk_sizes=[1024, 512, 256])
        else:
            return SentenceSplitter(chunk_size=kb.chunk_size, chunk_overlap=kb.chunk_overlap)

    async def ingest_document(self, doc_id: str, content: str, kb: KnowledgeBase, metadata: dict):
        """文档入库: 根据知识库配置构建 IngestionPipeline"""
        from llama_index.core.ingestion import IngestionPipeline
        from llama_index.core.schema import Document as LlamaDocument

        embedding_config = await LLMProviderConfig.get(id=kb.embedding_model_id)
        embed_model = self._build_embed_model(embedding_config)
        node_parser = self._build_node_parser(kb)

        metadata.update({"knowledge_base_id": str(kb.id), "doc_id": doc_id})
        llama_doc = LlamaDocument(text=content, metadata=metadata, doc_id=doc_id)

        pipeline = IngestionPipeline(
            transformations=[node_parser, embed_model],
            vector_store=self._vector_store,
        )
        await pipeline.arun(documents=[llama_doc])
        logger.info(f"Document ingested: doc_id={doc_id}, kb={kb.name}")

    async def delete_document(self, doc_id: str):
        """删除文档的所有向量"""
        if self._vector_store:
            await self._vector_store.adelete(doc_id)
            logger.info(f"Document vectors deleted: doc_id={doc_id}")

    async def delete_by_knowledge_base(self, kb_id: int):
        """删除知识库所有向量"""
        from llama_index.core.vector_stores import (
            ExactMatchFilter,
            MetadataFilters,
        )

        filters = MetadataFilters(filters=[ExactMatchFilter(key="knowledge_base_id", value=str(kb_id))])
        if self._vector_store:
            await self._vector_store.adelete(filters=filters)
            logger.info(f"Knowledge base vectors deleted: kb_id={kb_id}")

    async def query(
        self,
        question: str,
        knowledge_bases: list[KnowledgeBase],
        chat_model_config: LLMProviderConfig,
        system_prompt: str = None,
    ) -> dict:
        """RAG 问答"""
        from llama_index.core import VectorStoreIndex
        from llama_index.core.vector_stores import (
            ExactMatchFilter,
            MetadataFilters,
        )

        llm = self._build_llm(chat_model_config)
        kb_ids = [str(kb.id) for kb in knowledge_bases]
        max_top_k = max(kb.similarity_top_k for kb in knowledge_bases)
        use_hybrid = any(kb.retrieval_mode == "hybrid" for kb in knowledge_bases)
        min_threshold = min(kb.similarity_threshold for kb in knowledge_bases)

        filters = MetadataFilters(filters=[ExactMatchFilter(key="knowledge_base_id", value=kb_ids)])

        index = VectorStoreIndex.from_vector_store(
            vector_store=self._vector_store,
            embed_model=self._build_embed_model(
                await LLMProviderConfig.get(id=knowledge_bases[0].embedding_model_id)
            ),
        )

        query_mode = "hybrid" if use_hybrid else "default"
        query_engine = index.as_query_engine(
            llm=llm,
            similarity_top_k=max_top_k,
            filters=filters,
            vector_store_query_mode=query_mode,
            system_prompt=system_prompt,
        )
        response = await query_engine.aquery(question)

        sources = []
        for node in response.source_nodes:
            if node.score and node.score >= min_threshold:
                sources.append(
                    {
                        "score": node.score,
                        "text_preview": node.text[:200],
                        "metadata": node.metadata,
                    }
                )

        return {"answer": str(response), "sources": sources}

    async def chat(
        self,
        question: str,
        history: list[dict],
        knowledge_bases: list[KnowledgeBase],
        chat_model_config: LLMProviderConfig,
        system_prompt: str = None,
    ) -> dict:
        """多轮对话问答"""
        from llama_index.core import VectorStoreIndex
        from llama_index.core.chat_engine import CondensePlusContextChatEngine
        from llama_index.core.llms import ChatMessage as LlamaChatMessage
        from llama_index.core.vector_stores import (
            ExactMatchFilter,
            MetadataFilters,
        )

        llm = self._build_llm(chat_model_config)
        kb_ids = [str(kb.id) for kb in knowledge_bases]
        max_top_k = max(kb.similarity_top_k for kb in knowledge_bases)
        use_hybrid = any(kb.retrieval_mode == "hybrid" for kb in knowledge_bases)
        min_threshold = min(kb.similarity_threshold for kb in knowledge_bases)

        filters = MetadataFilters(filters=[ExactMatchFilter(key="knowledge_base_id", value=kb_ids)])

        index = VectorStoreIndex.from_vector_store(
            vector_store=self._vector_store,
            embed_model=self._build_embed_model(
                await LLMProviderConfig.get(id=knowledge_bases[0].embedding_model_id)
            ),
        )

        query_mode = "hybrid" if use_hybrid else "default"
        retriever = index.as_retriever(
            similarity_top_k=max_top_k,
            filters=filters,
            vector_store_query_mode=query_mode,
        )

        chat_history = [
            LlamaChatMessage(role=msg["role"], content=msg["content"]) for msg in history
        ]

        chat_engine = CondensePlusContextChatEngine.from_defaults(
            retriever=retriever,
            llm=llm,
            system_prompt=system_prompt,
        )
        response = await chat_engine.achat(question, chat_history=chat_history)

        sources = []
        for node in response.source_nodes:
            if node.score and node.score >= min_threshold:
                sources.append(
                    {
                        "score": node.score,
                        "text_preview": node.text[:200],
                        "metadata": node.metadata,
                    }
                )

        return {"answer": str(response), "sources": sources}

    async def test_model_connection(self, config: LLMProviderConfig) -> bool:
        """测试模型连接"""
        try:
            if config.is_embedding:
                embed_model = self._build_embed_model(config)
                await embed_model.aget_text_embedding("test")
            else:
                llm = self._build_llm(config)
                await llm.acomplete("Hello")
            return True
        except Exception as e:
            logger.error(f"Model connection test failed: {e}")
            return False


rag_service = RAGService()
