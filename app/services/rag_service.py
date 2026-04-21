from __future__ import annotations

import json
from typing import Any, Optional

from app.log import logger
from app.models.rag import Document, KnowledgeBase, LLMProviderConfig
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
            context_window=8192,
            is_function_calling_model=True,
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

        # 构建知识库过滤条件
        if len(kb_ids) == 1:
            filters = MetadataFilters(filters=[ExactMatchFilter(key="knowledge_base_id", value=kb_ids[0])])
        else:
            filters = MetadataFilters(
                filters=[ExactMatchFilter(key="knowledge_base_id", value=kb_id) for kb_id in kb_ids],
                condition="or"
            )

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
        """
        为每个知识库构建一个可被 Agent 调用的 FunctionTool。

        入参:
            knowledge_bases: 关联的知识库列表
            chat_model_config: 对话模型配置（用于构建 embed_model）

        返回:
            List[FunctionTool] — 每个 tool 对应一个知识库

        扩展点:
            可根据 kb.chunk_mode 等字段为不同知识库选择不同的检索策略
            （如 Q&A 检索、父子切片检索等），当前仅实现基础向量检索。
        """
        from llama_index.core import VectorStoreIndex
        from llama_index.core.tools import FunctionTool
        from llama_index.core.vector_stores import ExactMatchFilter, MetadataFilters

        tools = []
        for kb in knowledge_bases:
            # 构建该知识库的向量索引和检索器
            kb_filter = MetadataFilters(
                filters=[ExactMatchFilter(key="knowledge_base_id", value=str(kb.id))]
            )
            index = VectorStoreIndex.from_vector_store(
                vector_store=self._vector_store,
                embed_model=self._build_embed_model(
                    await LLMProviderConfig.get(id=kb.embedding_model_id)
                ),
            )
            query_mode = "hybrid" if kb.retrieval_mode == "hybrid" else "default"

            # --- 扩展点：根据 kb.chunk_mode 切换检索策略 ---
            # if kb.chunk_mode == "qa":
            #     retriever = ... (Q&A 检索器)
            # elif kb.chunk_mode == "parent_child":
            #     retriever = ... (父子切片检索器)
            # else:
            #     retriever = ... (默认向量检索)

            retriever = index.as_retriever(
                similarity_top_k=kb.similarity_top_k,
                filters=kb_filter,
                vector_store_query_mode=query_mode,
            )

            # 工厂函数：生成闭包，避免下划线参数出现在函数签名中
            # （FunctionTool 会扫描签名构建 Pydantic schema，不允许下划线字段名）
            kb_name = kb.name
            kb_desc = kb.description or kb.name
            kb_threshold = kb.similarity_threshold

            logger.debug(f"[kd_vector_tools_builder] Building tool for kb={kb_name} desc={kb_desc}")

            def _make_kd_query_tool_fn(captured_retriever, captured_kb_name, captured_threshold):
                async def kd_vector_query(
                    query: str,
                    metadata_filters: Optional[dict] = None,
                ) -> str:
                    """在知识库中执行向量检索，返回匹配文档片段的 JSON 字符串"""
                    logger.debug(f"[kd_vector_query] kb={captured_kb_name} Query: {query}")
                    try:
                        from llama_index.core.indices.query.schema import QueryBundle
                        from app.services.rag_node_processors import MetadataFilterPostProcessor

                        nodes = await captured_retriever.aretrieve(query)
                        # 清理 metadata，减少 token 消耗
                        processor = MetadataFilterPostProcessor(["doc_id"])
                        nodes = processor.postprocess_nodes(
                            nodes, query_bundle=QueryBundle(query)
                        )
                        results = []
                        for node in nodes:
                            score = getattr(node, "score", None)
                            if score and score >= captured_threshold:
                                node_obj = node.node if hasattr(node, "node") else node
                                node_text = node_obj.text if hasattr(node_obj, "text") else str(node_obj)
                                logger.debug(f"[kd_vector_query] kb={captured_kb_name} Score: {score} Text: {node_text[:100]} metadata: {node_obj.metadata}")
                                results.append({
                                    "score": round(score, 4),
                                    "text": node_text,
                                    "metadata": node_obj.metadata,
                                })
                        return json.dumps(results, ensure_ascii=False) if results else "[]"
                    except Exception as e:
                        logger.error(f"[kd_vector_query] Error in {captured_kb_name}: {e}")
                        return json.dumps([{"error": str(e)}], ensure_ascii=False)
                return kd_vector_query

            kd_query_fn = _make_kd_query_tool_fn(retriever, kb_name, kb_threshold)

            # 工具名：仅使用 ASCII 字符（function calling 协议不支持中文 tool name）
            # 中文信息放在 description 中供 LLM 理解工具用途
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

    # ------------------------------------------------------------------
    # 流式问答 — 基于 FunctionAgent + 知识库向量工具
    # ------------------------------------------------------------------

    async def chat_stream(
        self,
        question: str,
        history: list[dict],
        knowledge_bases: list[KnowledgeBase],
        chat_model_config: LLMProviderConfig,
        system_prompt: str = None,
    ):
        """多轮对话问答（流式）— 使用 FunctionAgent + 知识库向量工具替代 CondensePlusContextChatEngine"""
        from llama_index.core.agent.workflow import FunctionAgent, AgentStream
        from llama_index.core.llms import ChatMessage as LlamaChatMessage
        from llama_index.core.memory import ChatMemoryBuffer

        try:
            llm = self._build_llm(chat_model_config)

            # Step 1: 构建知识库向量查询工具
            kd_tools = await self.kd_vector_tools_builder(
                knowledge_bases=knowledge_bases,
                chat_model_config=chat_model_config,
            )
            
            if not kd_tools:
                yield {"type": "error", "content": "未构建到任何知识库查询工具"}
                return

            # Step 2: 构建历史对话（最多10条 = 5轮）
            max_history_messages = 10
            limited_history = history[-max_history_messages:] if len(history) > max_history_messages else history
            chat_history = []
            for msg in limited_history:
                role = "user" if msg["role"] == "user" else "assistant"
                chat_history.append(LlamaChatMessage(role=role, content=str(msg["content"])))

            # Step 3: 构建 Agent
            agent_prompt = (
                system_prompt
                or "你是一个智能问答助手。请使用提供的知识库查询工具来检索相关文档，然后基于检索结果回答用户问题。"
                "如果检索结果不足以回答问题，请如实说明。回答应准确、简洁、有条理。"
            )
            context_window = getattr(llm.metadata, "context_window", 4096)
            memory = ChatMemoryBuffer.from_defaults(
                token_limit=int(context_window * 0.9),
                chat_history=chat_history,
            )

            agent = FunctionAgent(
                tools=kd_tools,
                llm=llm,
                system_prompt=agent_prompt,
                memory=memory,
                verbose=True,
            )

            # Step 4: 运行 Agent（流式），从 AgentStream 事件中提取 delta
            handler = agent.run(
                user_msg=question,
                chat_history=chat_history,
            )

            sources_data = []
            async for event in handler.stream_events():
                if isinstance(event, AgentStream):
                    delta = event.delta or ""
                    if delta:
                        yield {"type": "delta", "content": delta}

            # 获取最终结果
            response = await handler
            # 从 Agent 的工具调用结果中提取 sources
            # FunctionAgent 的 response 是 AgentOutput
            final_text = str(response)     
            # 获取所有的工具调用
            doc_ids = set()
            for tool_call in response.tool_calls:
                tool_result = json.loads(tool_call.tool_output.blocks[0].text)
                for item in tool_result:
                    if isinstance(item, dict):        
                        doc_id = item.get("metadata", {}).get("doc_id")
                        doc_ids.add(int(doc_id))

            for doc_id in doc_ids:
                doc = await Document.get(id=doc_id)
                if doc:
                    sources_data.append({
                        "metadata": {
                            "title": doc.title,
                            "url": doc.source_meta.get("feishu_url"),
                        }
                    })

            yield {"type": "sources", "content": sources_data}

        except BaseException as e:
            logger.error(f"Chat stream error: {type(e).__name__}: {e}")
            yield {"type": "error", "content": str(e)}

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

                        