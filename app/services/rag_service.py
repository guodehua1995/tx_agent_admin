from __future__ import annotations

import json
from typing import Optional

from llama_index.core import VectorStoreIndex
from llama_index.core.vector_stores import ExactMatchFilter, MetadataFilters

from app.log import logger
from app.models.rag import Document, KnowledgeBase, LLMProviderConfig,DocumentPage
from app.services.llm_builder import build_embed_model, build_llm
from app.settings import settings
from app.agents.tools import KdVectorQueryToolProvider

DEFAULT_CONTEXT_WINDOW = 8192
MAX_HISTORY_MESSAGES = 10


def _build_kb_filters(kb_ids: list[str]) -> MetadataFilters:
    """构建知识库过滤条件"""
    if len(kb_ids) == 1:
        return MetadataFilters(filters=[ExactMatchFilter(key="knowledge_base_id", value=kb_ids[0])])
    return MetadataFilters(
        filters=[ExactMatchFilter(key="knowledge_base_id", value=kb_id) for kb_id in kb_ids],
        condition="or",
    )


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
        """文档入库: 根据知识库配置构建 IngestionPipeline

        metadata 应包含 BaseVectorMetadata 定义的基础字段:
            title, source_type, doc_type_code（必填）
            knowledge_base_id, doc_id 会自动注入
        """
        from llama_index.core.ingestion import IngestionPipeline
        from llama_index.core.schema import Document as LlamaDocument

        from app.schemas.vector_metadata import BaseVectorMetadata

        embedding_config = await LLMProviderConfig.get(id=kb.embedding_model_id)
        embed_model = build_embed_model(embedding_config)
        node_parser = self._build_node_parser(kb)

        # 确保必要字段存在，通过 BaseVectorMetadata 校验
        metadata.update({"knowledge_base_id": str(kb.id), "doc_id": doc_id})
        validated = BaseVectorMetadata(**metadata)
        llama_doc = LlamaDocument(text=content, metadata=validated.to_dict(), doc_id=doc_id)

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
        doc_templates: list = None,
    ) -> dict:
        """多轮对话问答（非流式）— 复用 chat_stream 的 FunctionAgent 架构"""
        try:
            answer_parts = []
            sources = []
            tool_calls_data = []

            async for event in self.chat_stream(
                question=question,
                history=history,
                knowledge_bases=knowledge_bases,
                chat_model_config=chat_model_config,
                system_prompt=system_prompt,
                doc_templates=doc_templates,
            ):
                if event["type"] == "delta":
                    answer_parts.append(event["content"])
                elif event["type"] == "tool_calls":
                    tool_calls_data = event["content"]
                elif event["type"] == "sources":
                    sources = event["content"]
                elif event["type"] == "error":
                    return {"answer": event["content"], "sources": [], "tool_calls": []}

            return {"answer": "".join(answer_parts), "sources": sources, "tool_calls": tool_calls_data}
        except Exception as e:
            logger.error(f"Chat error: {e}")
            return {"answer": str(e), "sources": [], "tool_calls": []}
    
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
            msg_type = msg.get("type") or msg.get("role", "user")
            content = str(msg["content"])
            if msg_type == "user":
                chat_history.append(LlamaChatMessage(role="user", content=content))
            elif msg_type == "assistant":
                chat_history.append(LlamaChatMessage(role="assistant", content=content))
            elif msg_type == "tool_call":
                # 工具调用映射为 assistant （含调用信息）
                try:
                    data = json.loads(content)
                    call_desc = f"[调用工具: {data['tool_name']}] {data.get('tool_input', '')}"
                except (json.JSONDecodeError, KeyError):
                    call_desc = content
                chat_history.append(LlamaChatMessage(role="assistant", content=call_desc))
            elif msg_type == "tool_call_result":
                # 工具结果映射为 tool 角色
                try:
                    data = json.loads(content)
                    result_text = data.get("result", content)
                except (json.JSONDecodeError, KeyError):
                    result_text = content
                chat_history.append(LlamaChatMessage(role="tool", content=result_text))
            else:
                chat_history.append(LlamaChatMessage(role="assistant", content=content))

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
        page_ids = set()
        for tool_call in tool_calls:
            try:
                tool_result = json.loads(tool_call.tool_output.blocks[0].text)
                for item in tool_result:
                    if isinstance(item, dict):
                        doc_id = item.get("metadata", {}).get("doc_id")
                        page_id = item.get("metadata", {}).get("page_id")
                        if doc_id:
                            doc_ids.add(int(doc_id))
                        if page_id:
                            page_ids.add(int(page_id))
            except (json.JSONDecodeError, ValueError, TypeError):
                continue

        sources_data = []

        if page_ids:
            pages = await DocumentPage.filter(id__in=list(page_ids)).all()
            for page in pages:
               url = page.screenshot_url
               sources_data.append({
                    "metadata": {
                        "title": f"页码{page.page_number}",
                        "url": url,
                        "type": "img_url"
                    }
                })
        
        if doc_ids:
            docs = await Document.filter(id__in=list(doc_ids)).all()
            for doc in docs:
                url = doc.source_meta.get("feishu_url") if doc.source_meta else None
                sources_data.append({
                    "metadata": {
                        "title": doc.title,
                        "url": url,
                        "type": "doc_url"
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
        doc_templates: list = None,
    ):
        """多轮对话问答（流式）— 使用 FunctionAgent + 知识库向量工具 + 文档模板工具"""
        from llama_index.core.agent.workflow import AgentStream

        try:
            provider = KdVectorQueryToolProvider(self._vector_store)
            kd_tools = await provider.build_llamaindex_tools(
                knowledge_bases=knowledge_bases,
                chat_model_config=chat_model_config,
            )

            # kd_tools = await self.kd_vector_tools_builder(
            #     knowledge_bases=knowledge_bases,
            #     chat_model_config=chat_model_config,
            # )

            if not kd_tools:
                yield {"type": "error", "content": "未构建到任何知识库查询工具"}
                return

            # 通过统一工具入口构建所有工具
            from app.agents.tools import build_chat_tools
            kd_tools = await build_chat_tools(
                framework="llamaindex",
                vector_store=self._vector_store,
                knowledge_bases=knowledge_bases,
                chat_model_config=chat_model_config,
                doc_templates=doc_templates,
            )

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

            # 收集工具调用数据
            tool_calls_data = []
            for tc in response.tool_calls:
                try:
                    tool_output_text = tc.tool_output.blocks[0].text if tc.tool_output else ""
                except (IndexError, AttributeError):
                    tool_output_text = ""
                tool_calls_data.append({
                    "tool_name": tc.tool_name,
                    "tool_input": str(tc.tool_input),
                    "tool_output": tool_output_text,
                })
            yield {"type": "tool_calls", "content": tool_calls_data}

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

                        