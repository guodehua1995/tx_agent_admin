import time

from app.controllers.ai_config import ai_config_controller
from app.controllers.conversation import conversation_controller
from app.controllers.feishu_bot import feishu_bot_controller
from app.controllers.review import review_controller
from app.models.admin import User
from app.models.enums import DocumentSourceType, DocumentStatus, DocumentTypeCode, FeishuPublishStatus
from app.models.global_config import GlobalConfig
from app.models.rag import (
    Agent,
    ChatMessage,
    Document,
    KnowledgeBase,
    LLMProviderConfig,
    StructuredResult,
)
from app.services.agent_service import agent_service
from app.services.feishu_service import feishu_service
from app.services.rag_service import rag_service
from app.services.structuring import run_structuring
from app.settings import settings

from app.log import logger


class DocumentPipeline:
    """文档处理流程编排"""

    async def process_document(self, doc_id: int):
        """文档上传后处理: 根据 doc_type_code 路由到对应处理函数"""
        doc = await Document.get(id=doc_id)
        try:
            # 根据文档类型 code 路由到对应处理流程
            if doc.doc_type_code == DocumentTypeCode.PPT:
                await self._process_ppt_document(doc)
                return

            # 默认流程（如 feishu_doc）：获取内容 → 结构化(可选) → 待审核
            if doc.source_type == DocumentSourceType.FEISHU_DOC:
                content = await self._fetch_feishu_content(doc)
            elif doc.source_type == DocumentSourceType.FILE_UPLOAD:
                content = await self._read_uploaded_file(doc)
            elif doc.source_type == DocumentSourceType.WEB_URL:
                content = await self._fetch_web_content(doc)
            else:
                raise ValueError(f"不支持的来源类型: {doc.source_type}")

            doc.content = content
            doc.status = DocumentStatus.FETCHED
            await doc.save()

            # 2. 检查是否需要结构化（通过 structuring 注册表判断）
            from app.services.structuring import STRUCTURING_HANDLERS
            if doc.doc_type_code in STRUCTURING_HANDLERS:
                doc.status = DocumentStatus.STRUCTURING
                await doc.save()
                await self._run_structuring(doc)

            # 3. 进入待审核
            doc.status = DocumentStatus.PENDING_REVIEW
            await doc.save()
            logger.info(f"Document processed: id={doc_id}, status=pending_review")

        except Exception as e:
            doc.status = DocumentStatus.FAILED
            doc.error_message = str(e)
            await doc.save()
            logger.exception(f"Document processing failed: id={doc_id}")

    async def _fetch_feishu_content(self, doc: Document) -> str:
        """从飞书拉取文档内容"""
        meta = doc.source_meta or {}
        feishu_url = meta.get("feishu_url", "")
        doc_token, doc_type = feishu_service.parse_feishu_url(feishu_url)

        # 需要通过某个飞书机器人的凭证获取 token
        global_config = await GlobalConfig.get(config_key="feishu_pull_bot")
        if not global_config:
            raise ValueError("没有配置飞书拉取机器人")
        bot_configs = await feishu_bot_controller.get_by_app_id(app_id=global_config.config_value)
        if not bot_configs:
            raise ValueError("没有可用的飞书机器人配置")

        access_token = await feishu_service.get_tenant_access_token(bot_configs.app_id, bot_configs.app_secret)
        content = await feishu_service.fetch_document_content(doc_token, doc_type, access_token)
        agent_content = await agent_service.run_agent("doc_to_markdown",{"document_content": content})
        doc.source_meta = {**meta, "feishu_doc_token": doc_token, "feishu_doc_type": doc_type}
        if not agent_content["success"]:
            raise ValueError(f"Agent execution failed: agent_name=doc_to_markdown")
        return agent_content["markdown_content"]

    async def _read_uploaded_file(self, doc: Document) -> str:
        """读取上传的文件内容"""
        meta = doc.source_meta or {}
        file_path = meta.get("file_path", "")
        if not file_path:
            raise ValueError("文件路径为空")

        with open(file_path, "r", encoding="utf-8", errors="ignore") as f:
            return f.read()

    async def _fetch_web_content(self, doc: Document) -> str:
        """抓取网页内容"""
        import httpx

        meta = doc.source_meta or {}
        url = meta.get("url", "")
        if not url:
            raise ValueError("URL 为空")

        async with httpx.AsyncClient() as client:
            resp = await client.get(url, follow_redirects=True)
            return resp.text

    async def _process_ppt_document(self, doc: Document):
        """PPT 文档专用处理流程: PPT → 图片 → LLM → Markdown → 待审核"""
        from app.services.ppt_processor import ppt_processor

        meta = doc.source_meta or {}

        try:
            # 根据来源获取 PPT 内容
            if doc.source_type == DocumentSourceType.FEISHU_DOC:
                feishu_url = meta.get("feishu_url", "")
                if not feishu_url:
                    raise ValueError("飞书 PPT URL 为空")
                markdown_content = await ppt_processor.process_from_feishu_url(feishu_url)
                source_path = feishu_url
            elif doc.source_type == DocumentSourceType.FILE_UPLOAD:
                file_path = meta.get("file_path", "")
                if not file_path:
                    raise ValueError("PPT 文件路径为空")
                markdown_content = await ppt_processor.process_from_file_path(file_path)
                source_path = file_path
            else:
                raise ValueError(f"PPT 文档不支持的来源类型: {doc.source_type}")

            # 保存处理后的 markdown 内容
            doc.content = markdown_content
            doc.source_meta = {**meta, "ppt_source_path": source_path}
            doc.status = DocumentStatus.PENDING_REVIEW
            await doc.save()
            logger.info(f"PPT document processed: id={doc.id}, status=pending_review")

        except Exception as e:
            doc.status = DocumentStatus.FAILED
            doc.error_message = str(e)
            await doc.save()
            logger.exception(f"PPT document processing failed: id={doc.id}")

    async def _run_structuring(self, doc: Document):
        """执行结构化处理"""
        # 获取默认的结构化模型
        chat_models = await ai_config_controller.get_active_chat_models()
        if not chat_models:
            raise ValueError("没有可用的 Chat 模型配置")
        model_config = chat_models[0]

        start_time = time.time()
        result = await run_structuring(doc.doc_type_code, doc.content, model_config)
        elapsed_ms = int((time.time() - start_time) * 1000)

        await StructuredResult.create(
            document_id=doc.id,
            structured_content=result.content,
            structuring_model_id=model_config.id,
            prompt_used=result.prompt_used,
            token_usage=result.token_usage,
            processing_time_ms=elapsed_ms,
        )

    async def vectorize_document(self, doc_id: int):
        """审核通过后: 确定最终内容 → LlamaIndex 入库"""

        doc = await Document.get(id=doc_id)
        logger.info(f"Vectorizing document: id={doc_id}, name={doc.title}")
        try:
            doc.status = DocumentStatus.VECTORIZING
            await doc.save()

            # 检查文档类型，PPT 走专用分页向量化逻辑
            if doc.doc_type_code == DocumentTypeCode.PPT:
                await self._vectorize_ppt_document(doc)
            else:
                # 确定最终内容: 审核编辑 > 结构化 > 原始
                final_content = doc.content
                reviews = await review_controller.get_by_document(doc_id)
                if reviews and reviews[0].edited_content:
                    final_content = reviews[0].edited_content
                else:
                    structured = await StructuredResult.filter(document_id=doc_id).first()
                    if structured:
                        final_content = structured.structured_content

                kb = await KnowledgeBase.get(id=doc.knowledge_base_id)
                metadata = {"title": doc.title, "source_type": doc.source_type}

                await rag_service.ingest_document(
                    doc_id=str(doc.id),
                    content=final_content,
                    kb=kb,
                    metadata=metadata,
                )

            doc.status = DocumentStatus.COMPLETED
            await doc.save()
            logger.info(f"Document vectorized: id={doc_id}")

        except Exception as e:
            doc.status = DocumentStatus.FAILED
            doc.error_message = str(e)
            await doc.save()
            logger.exception(f"Document vectorization failed: id={doc_id}")

    async def _vectorize_ppt_document(self, doc: Document):
        """PPT 文档专用向量化: 按页拆分为独立文档入库"""
        from llama_index.core.ingestion import IngestionPipeline
        from llama_index.core.node_parser import MarkdownNodeParser
        from llama_index.core.schema import Document as LlamaDocument

        from app.services.ppt_processor import ppt_processor

        kb = await KnowledgeBase.get(id=doc.knowledge_base_id)
        embedding_config = await LLMProviderConfig.get(id=kb.embedding_model_id)
        from app.services.llm_builder import build_embed_model
        embed_model = build_embed_model(embedding_config)

        # 确定最终内容（审核编辑优先）
        final_content = doc.content
        reviews = await review_controller.get_by_document(doc.id)
        if reviews and reviews[0].edited_content:
            final_content = reviews[0].edited_content

        # 按页拆分
        meta = doc.source_meta or {}
        source_path = meta.get("ppt_source_path", meta.get("feishu_url", meta.get("file_path", "")))
        page_docs = ppt_processor.get_page_documents(final_content, source_path)

        if not page_docs:
            raise ValueError("PPT 文档解析后没有有效页面内容")

        llama_docs = []
        for page_data in page_docs:
            page_metadata = {
                "title": doc.title,
                "source_type": doc.source_type,
                "knowledge_base_id": str(kb.id),
                "doc_id": str(doc.id),
                **page_data["metadata"],
            }
            llama_docs.append(
                LlamaDocument(
                    text=page_data["text"],
                    metadata=page_metadata,
                    doc_id=f"{doc.id}_page_{page_data['metadata']['page_number']}",
                )
            )

        # 对超长页面使用 Markdown 切割器，短页面直接入库
        node_parser = MarkdownNodeParser()
        pipeline = IngestionPipeline(
            transformations=[node_parser, embed_model],
            vector_store=rag_service._vector_store,
        )
        await pipeline.arun(documents=llama_docs)
        logger.info(
            f"PPT document vectorized: doc_id={doc.id}, pages={len(page_docs)}"
        )

    async def publish_to_feishu(self, structured_result_id: int):
        """将结构化结果发布到飞书云文档"""
        result = await StructuredResult.get(id=structured_result_id)
        doc = await Document.get(id=result.document_id)

        try:
            result.feishu_publish_status = FeishuPublishStatus.PUBLISHING
            await result.save()

            bot_configs = await feishu_bot_controller.model.filter(is_active=True).first()
            if not bot_configs:
                raise ValueError("没有可用的飞书机器人配置")

            access_token = await feishu_service.get_tenant_access_token(bot_configs.app_id, bot_configs.app_secret)
            url = await feishu_service.create_doc_in_folder(
                folder_token=settings.FEISHU_STRUCTURED_FOLDER_TOKEN,
                title=doc.title,
                content=result.structured_content,
                access_token=access_token,
            )

            result.feishu_publish_status = FeishuPublishStatus.PUBLISHED
            result.feishu_publish_url = url
            await result.save()
            logger.info(f"Published to Feishu: result_id={structured_result_id}, url={url}")

        except Exception as e:
            result.feishu_publish_status = FeishuPublishStatus.FAILED
            await result.save()
            logger.exception(f"Feishu publish failed: result_id={structured_result_id}")

    async def handle_bot_message(self, bot_id: int, feishu_open_id: str, chat_id: str, question: str) -> dict:
        """飞书机器人消息处理"""
        # 1. bot_config → agent → knowledge_bases
        bot = await feishu_bot_controller.get(id=bot_id)
        agent = await Agent.get(id=bot.agent_id)
        knowledge_bases = await agent.knowledge_bases.all()
        if not knowledge_bases:
            return {"answer": "该 Agent 未关联任何知识库", "sources": []}

        # 2. feishu_open_id → user
        user = await User.filter(feishu_open_id=feishu_open_id).first()
        if not user:
            # user = await User.create(
            #     username=f"feishu_{feishu_open_id[:8]}",
            #     email=f"{feishu_open_id[:8]}@feishu.local",
            #     feishu_open_id=feishu_open_id,
            #     is_active=True,
            # )
            raise ValueError("用户不存在")

        # 3. 获取/创建 conversation
        conv = await conversation_controller.get_or_create(agent_id=agent.id, user_id=user.id)

        # 4. 加载历史消息
        recent_messages = await conversation_controller.get_messages(conv.id, limit=agent.max_history_turns * 2)
        history = [{"role": msg.role, "content": msg.content} for msg in reversed(list(recent_messages))]

        # 5. RAG 问答
        chat_model = await LLMProviderConfig.get(id=agent.chat_model_id)
        start_time = time.time()
        result = await rag_service.chat(
            question=question,
            history=history,
            knowledge_bases=list(knowledge_bases),
            chat_model_config=chat_model,
            system_prompt=agent.system_prompt,
        )
        elapsed_ms = int((time.time() - start_time) * 1000)

        # 6. 保存消息记录
        await ChatMessage.create(conversation_id=conv.id, role="user", content=question, feishu_message_id=None)
        await ChatMessage.create(
            conversation_id=conv.id,
            role="assistant",
            content=result["answer"],
            retrieved_chunks=result["sources"],
            response_time_ms=elapsed_ms,
        )

        from datetime import datetime

        conv.message_count += 2
        conv.last_active_at = datetime.now()
        await conv.save()

        return result


document_pipeline = DocumentPipeline()
