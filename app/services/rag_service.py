from __future__ import annotations

import json
from typing import Optional

from llama_index.core import VectorStoreIndex
from llama_index.core.vector_stores import ExactMatchFilter, MetadataFilters

from app.log import logger
from app.models.rag import Document, KnowledgeBase, LLMProviderConfig
from app.services.llm_builder import build_embed_model, build_llm
from app.settings import settings

DEFAULT_CONTEXT_WINDOW = 8192
MAX_HISTORY_MESSAGES = 10
METADATA_KEEP_KEYS = ["doc_id"]


def _build_kb_filters(kb_ids: list[str]) -> MetadataFilters:
    """构建知识库过滤条件"""
    if len(kb_ids) == 1:
        return MetadataFilters(filters=[ExactMatchFilter(key="knowledge_base_id", value=kb_ids[0])])
    return MetadataFilters(
        filters=[ExactMatchFilter(key="knowledge_base_id", value=kb_id) for kb_id in kb_ids],
        condition="or",
    )


def _make_kd_query_tool_fn(retriever, kb_name: str, threshold: float):
    """工厂函数：生成知识库向量查询工具"""
    async def kd_vector_query(query: str, metadata_filters: Optional[dict] = None) -> str:
        """在知识库中执行向量检索，返回匹配文档片段的 JSON 字符串"""
        from llama_index.core.indices.query.schema import QueryBundle
        from app.services.rag_node_processors import MetadataFilterPostProcessor

        # logger.debug(f"[kd_vector_query] kb={kb_name} Query: {query}")
        try:
            nodes = await retriever.aretrieve(query)
            processor = MetadataFilterPostProcessor(METADATA_KEEP_KEYS)
            nodes = processor.postprocess_nodes(nodes, query_bundle=QueryBundle(query))

            results = []
            for node in nodes:
                score = getattr(node, "score", None)
                if score and score >= threshold:
                    node_obj = node.node if hasattr(node, "node") else node
                    node_text = node_obj.text if hasattr(node_obj, "text") else str(node_obj)
                    # logger.debug(
                    #     f"[kd_vector_query] kb={kb_name} Score: {score} "
                    #     f"Text: {node_text[:100]} metadata: {node_obj.metadata}"
                    # )
                    results.append({
                        "score": round(score, 4),
                        "text": node_text,
                        "metadata": node_obj.metadata,
                    })
            return json.dumps(results, ensure_ascii=False) if results else "[]"
        except Exception as e:
            logger.error(f"[kd_vector_query] Error in {kb_name}: {e}")
            return json.dumps([{"error": str(e)}], ensure_ascii=False)

    return kd_vector_query


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

    async def _build_index(self, embedding_model_id: int):
        """构建 VectorStoreIndex"""
        return VectorStoreIndex.from_vector_store(
            vector_store=self._vector_store,
            embed_model=build_embed_model(
                await LLMProviderConfig.get(id=embedding_model_id)
            ),
        )

    async def ingest_document(self, doc_id: str, content: str, kb: KnowledgeBase, metadata: dict):
        """文档入库: 根据知识库配置构建 IngestionPipeline"""
        from llama_index.core.ingestion import IngestionPipeline
        from llama_index.core.schema import Document as LlamaDocument

        embedding_config = await LLMProviderConfig.get(id=kb.embedding_model_id)
        embed_model = build_embed_model(embedding_config)
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
        llm = build_llm(chat_model_config)
        kb_ids = [str(kb.id) for kb in knowledge_bases]
        max_top_k = max(kb.similarity_top_k for kb in knowledge_bases)
        use_hybrid = any(kb.retrieval_mode == "hybrid" for kb in knowledge_bases)
        min_threshold = min(kb.similarity_threshold for kb in knowledge_bases)

        filters = _build_kb_filters(kb_ids)
        index = await self._build_index(knowledge_bases[0].embedding_model_id)

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
                sources.append({
                    "score": node.score,
                    "text_preview": node.text[:200],
                    "metadata": node.metadata,
                })

        return {"answer": str(response), "sources": sources}

    async def chat(
        self,
        question: str,
        history: list[dict],
        knowledge_bases: list[KnowledgeBase],
        chat_model_config: LLMProviderConfig,
        system_prompt: str = None,
    ) -> dict:
        """多轮对话问答（非流式）— 复用 chat_stream 的 FunctionAgent 架构"""
        try:
            answer_parts = []
            sources = []

            async for event in self.chat_stream(
                question=question,
                history=history,
                knowledge_bases=knowledge_bases,
                chat_model_config=chat_model_config,
                system_prompt=system_prompt,
            ):
                if event["type"] == "delta":
                    answer_parts.append(event["content"])
                elif event["type"] == "sources":
                    sources = event["content"]
                elif event["type"] == "error":
                    return {"answer": event["content"], "sources": []}

            return {"answer": "".join(answer_parts), "sources": sources}
        except Exception as e:
            logger.error(f"Chat error: {e}")
            return {"answer": str(e), "sources": []}

    # ------------------------------------------------------------------
    # 知识库向量查询工具构建器
    # ------------------------------------------------------------------

    async def kd_vector_tools_builder(
        self,
        knowledge_bases: list[KnowledgeBase],
        chat_model_config: LLMProviderConfig,
    ) -> list:
        """为每个知识库构建一个可被 Agent 调用的 FunctionTool"""
        from llama_index.core.tools import FunctionTool

        tools = []
        for kb in knowledge_bases:
            index = await self._build_index(kb.embedding_model_id)
            query_mode = "hybrid" if kb.retrieval_mode == "hybrid" else "default"

            retriever = index.as_retriever(
                similarity_top_k=kb.similarity_top_k,
                filters=MetadataFilters(
                    filters=[ExactMatchFilter(key="knowledge_base_id", value=str(kb.id))]
                ),
                vector_store_query_mode=query_mode,
            )

            kb_name = kb.name
            kb_desc = kb.description or kb.name
            kb_threshold = kb.similarity_threshold

            logger.debug(f"[kd_vector_tools_builder] Building tool for kb={kb_name} desc={kb_desc}")

            kd_query_fn = _make_kd_query_tool_fn(retriever, kb_name, kb_threshold)

            tool_name = f"kd_query_{kb.id}"
            tool_desc = (
                f"在「{kb_name}」知识库中检索与问题相关的文档内容。"
                f"{kb_desc}。"
                f"输入参数 query 为检索关键词/问题，metadata_filters 为可选的元数据过滤条件。"
            )

            tool = FunctionTool.from_defaults(
                fn=kd_query_fn,
                name=tool_name,
                description=tool_desc,
            )
            tools.append(tool)
            logger.debug(f"[kd_vector_tools_builder] Built tool: {tool_name} for kb={kb_name} desc={kb_desc}")

        return tools

    async def _build_chat_agent(
        self,
        history: list[dict],
        chat_model_config: LLMProviderConfig,
        system_prompt: str = None,
        tools: list = None,
    ):
        """构建 FunctionAgent 及其依赖（memory、chat_history）"""
        from llama_index.core.agent.workflow import FunctionAgent
        from llama_index.core.llms import ChatMessage as LlamaChatMessage
        from llama_index.core.memory import ChatMemoryBuffer

        llm = build_llm(chat_model_config)

        limited_history = history[-MAX_HISTORY_MESSAGES:] if len(history) > MAX_HISTORY_MESSAGES else history
        chat_history = []
        for msg in limited_history:
            role = "user" if msg["role"] == "user" else "assistant"
            chat_history.append(LlamaChatMessage(role=role, content=str(msg["content"])))

        agent_prompt = (
            system_prompt
            or "你是一个智能问答助手。请使用提供的知识库查询工具来检索相关文档，然后基于检索结果回答用户问题。"
            "如果检索结果不足以回答问题，请如实说明。回答应准确、简洁、有条理。"
        )
        context_window = getattr(llm.metadata, "context_window", DEFAULT_CONTEXT_WINDOW)
        memory = ChatMemoryBuffer.from_defaults(
            token_limit=int(context_window * 0.9),
            chat_history=chat_history,
        )

        agent = FunctionAgent(
            tools=tools or [],
            llm=llm,
            system_prompt=agent_prompt,
            memory=memory,
            verbose=True,
        )
        return agent, chat_history

    async def _extract_sources_from_tool_calls(self, tool_calls) -> list:
        """从 Agent 工具调用结果中提取 sources"""
        doc_ids = set()
        for tool_call in tool_calls:
            try:
                tool_result = json.loads(tool_call.tool_output.blocks[0].text)
                for item in tool_result:
                    if isinstance(item, dict):
                        doc_id = item.get("metadata", {}).get("doc_id")
                        if doc_id:
                            doc_ids.add(int(doc_id))
            except (json.JSONDecodeError, ValueError, TypeError):
                continue

        sources_data = []
        if doc_ids:
            docs = await Document.filter(id__in=list(doc_ids)).all()
            for doc in docs:
                url = doc.source_meta.get("feishu_url") if doc.source_meta else None
                sources_data.append({
                    "metadata": {
                        "title": doc.title,
                        "url": url,
                    }
                })
        return sources_data

    async def chat_stream(
        self,
        question: str,
        history: list[dict],
        knowledge_bases: list[KnowledgeBase],
        chat_model_config: LLMProviderConfig,
        system_prompt: str = None,
    ):
        """多轮对话问答（流式）— 使用 FunctionAgent + 知识库向量工具"""
        from llama_index.core.agent.workflow import AgentStream

        try:
            kd_tools = await self.kd_vector_tools_builder(
                knowledge_bases=knowledge_bases,
                chat_model_config=chat_model_config,
            )

            if not kd_tools:
                yield {"type": "error", "content": "未构建到任何知识库查询工具"}
                return

            agent, chat_history = await self._build_chat_agent(
                history=history,
                chat_model_config=chat_model_config,
                system_prompt=system_prompt,
                tools=kd_tools,
            )

            handler = agent.run(
                user_msg=question,
                chat_history=chat_history,
            )

            async for event in handler.stream_events():
                if isinstance(event, AgentStream):
                    delta = event.delta or ""
                    if delta:
                        yield {"type": "delta", "content": delta}

            response = await handler
            sources_data = await self._extract_sources_from_tool_calls(response.tool_calls)
            yield {"type": "sources", "content": sources_data}

        except Exception as e:
            logger.error(f"Chat stream error: {type(e).__name__}: {e}")
            yield {"type": "error", "content": str(e)}

    async def test_model_connection(self, config: LLMProviderConfig) -> bool:
        """测试模型连接"""
        try:
            if config.is_embedding:
                embed_model = build_embed_model(config)
                await embed_model.aget_text_embedding("test")
            else:
                llm = build_llm(config)
                await llm.acomplete("Hello")
            return True
        except Exception as e:
            logger.error(f"Model connection test failed: {e}")
            return False


rag_service = RAGService()

                        