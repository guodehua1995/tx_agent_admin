import time
from pathlib import Path

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
    DocumentPage,
    KnowledgeBase,
    LLMProviderConfig,
    StructuredResult,
)
from app.services.agent_service import agent_service
from app.services.document_converter import document_converter
from app.services.feishu_service import feishu_service
from app.services.rag_service import rag_service
from app.services.structuring import run_structuring
from app.settings import settings

from app.log import logger

# 文档转换器支持的文件扩展名（用于 file 类型判断）
CONVERTIBLE_EXTENSIONS = {"docx", "doc", "pdf", "pptx", "ppt", "xlsx", "xls", "csv", "txt", "md", "png", "jpg", "jpeg"}


class DocumentPipeline:
    """文档处理流程编排"""

    async def process_document(self, doc_id: int):
        """文档上传后处理: 根据来源和类型路由到对应处理函数"""
        doc = await Document.get(id=doc_id)
        try:
            # 飞书文档来源 — 根据 URL 解析结果路由
            if doc.source_type == DocumentSourceType.FEISHU_DOC:
                content = await self._fetch_feishu_content(doc)
            elif doc.source_type == DocumentSourceType.FILE_UPLOAD:
                content = await self._process_uploaded_file(doc)
            elif doc.source_type == DocumentSourceType.WEB_URL:
                content = await self._fetch_web_content(doc)
            else:
                raise ValueError(f"不支持的来源类型: {doc.source_type}")

            doc.content = content
            doc.status = DocumentStatus.FETCHED
            await doc.save()

            # 检查是否需要结构化（通过 structuring 注册表判断）
            from app.services.structuring import STRUCTURING_HANDLERS
            if doc.doc_type_code in STRUCTURING_HANDLERS:
                doc.status = DocumentStatus.STRUCTURING
                await doc.save()
                await self._run_structuring(doc)

            # 进入待审核
            doc.status = DocumentStatus.PENDING_REVIEW
            await doc.save()
            logger.info(f"Document processed: id={doc_id}, status=pending_review")

        except Exception as e:
            doc.status = DocumentStatus.FAILED
            doc.error_message = str(e)
            await doc.save()
            logger.exception(f"Document processing failed: id={doc_id}")

    async def _get_feishu_access_token(self) -> tuple:
        """获取飞书拉取机器人的 access_token 和 bot_config"""
        global_config = await GlobalConfig.get(config_key="feishu_pull_bot")
        if not global_config:
            raise ValueError("没有配置飞书拉取机器人")
        bot_configs = await feishu_bot_controller.get_by_app_id(app_id=global_config.config_value)
        if not bot_configs:
            raise ValueError("没有可用的飞书机器人配置")

        access_token = await feishu_service.get_tenant_access_token(bot_configs.app_id, bot_configs.app_secret)
        return access_token, bot_configs

    async def _fetch_feishu_content(self, doc: Document) -> str:
        """从飞书拉取文档内容（根据解析出的 doc_type 路由）"""
        meta = doc.source_meta or {}
        feishu_url = meta.get("feishu_url", "")
        doc_token, doc_type = feishu_service.parse_feishu_url(feishu_url)

        access_token, _ = await self._get_feishu_access_token()

        # file 类型：下载文件 → 文档转换器
        if doc_type == "file":
            return await self._process_feishu_file(doc, doc_token, access_token)

        # slide 类型：下载文件 → 文档转换器（slide 不支持 export，但如果是 /file/ 格式就走上面）
        # 注意：/slides/ URL 的 export API 已不可用，标记为失败
        if doc_type == "slide":
            raise ValueError(
                "飞书云文档PPT(slides类型)不支持通过API导出。"
                "请使用飞书文件格式的链接(https://xxx.feishu.cn/file/xxx)"
            )

        # docx/wiki/sheet 类型：走原有 API 拉取内容
        content = await feishu_service.fetch_document_content(doc_token, doc_type, access_token)
        agent_content = await agent_service.run_agent("doc_to_markdown", {"document_content": content})
        doc.source_meta = {**meta, "feishu_doc_token": doc_token, "feishu_doc_type": doc_type}
        if not agent_content["success"]:
            raise ValueError("Agent execution failed: agent_name=doc_to_markdown")
        return agent_content["markdown_content"]

    async def _process_feishu_file(self, doc: Document, file_token: str, access_token: str) -> str:
        """处理飞书 file 类型：下载文件 → 文档转换器 → Markdown"""
        meta = doc.source_meta or {}

        # 下载文件
        file_bytes, filename = await feishu_service.download_file(file_token, access_token)
        logger.info(f"Feishu file downloaded: token={file_token}, filename={filename}, size={len(file_bytes)}")

        # 从文件名提取扩展名
        ext = Path(filename).suffix.lstrip(".").lower()
        if not ext or ext not in CONVERTIBLE_EXTENSIONS:
            raise ValueError(f"不支持的文件类型: {filename} (扩展名: {ext})")

        # 调用文档转换器
        pages = await document_converter.convert(file_bytes, ext, filename)

        # 保存页面截图和页记录（若有 image_bytes）
        await self._save_page_records(doc, pages)

        markdown_content = document_converter.pages_to_markdown(pages)

        # 更新元数据
        doc.source_meta = {
            **meta,
            "feishu_file_token": file_token,
            "filename": filename,
            "file_type": ext,
            "page_count": len(pages),
        }

        return markdown_content

    async def _process_uploaded_file(self, doc: Document) -> str:
        """处理上传的文件：读取 → 文档转换器 → Markdown"""
        meta = doc.source_meta or {}
        file_path = meta.get("file_path", "")
        if not file_path:
            raise ValueError("文件路径为空")

        ext = Path(file_path).suffix.lstrip(".").lower()

        # 如果是文档转换器支持的类型，走转换器
        if ext in CONVERTIBLE_EXTENSIONS:
            with open(file_path, "rb") as f:
                file_bytes = f.read()
            filename = Path(file_path).name
            pages = await document_converter.convert(file_bytes, ext, filename)
            await self._save_page_records(doc, pages)
            markdown_content = document_converter.pages_to_markdown(pages)
           
            doc_token, doc_type = feishu_service.parse_feishu_url(file_path)
            doc.source_meta = {**meta,"feishu_doc_token": doc_token, "feishu_doc_type": doc_type, "file_type": ext, "page_count": len(pages)}
            return markdown_content

        # 其他类型尝试作为纯文本读取
        with open(file_path, "r", encoding="utf-8", errors="ignore") as f:
            return f.read()

    async def _save_page_records(self, doc: Document, pages):
        """保存页面截图并创建 DocumentPage 记录"""
        from app.services.file_storage import file_storage

        has_images = any(getattr(p, "image_bytes", None) for p in pages)
        if not has_images and len(pages) <= 1:
            return

        for page in pages:
            screenshot_url = None
            if page.image_bytes:
                path = f"pages/doc_{doc.id}/page_{page.page_number}.png"
                screenshot_url = await file_storage.save(path, page.image_bytes)

            await DocumentPage.create(
                document_id=doc.id,
                page_number=page.page_number,
                total_pages=page.total_pages,
                content=page.content,
                screenshot_url=screenshot_url,
            )

        logger.info(f"Page records saved: doc_id={doc.id}, pages={len(pages)}")

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

    async def _run_structuring(self, doc: Document):
        """执行结构化处理"""
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

            kb = await KnowledgeBase.get(id=doc.knowledge_base_id)

            # 分页类型文档：从 DocumentPage 表逐页读取内容向量化
            if DocumentTypeCode.is_paged_type(doc.doc_type_code):
                await self._vectorize_from_pages(doc, kb)
            else:
                # 非分页文档：走原有逻辑（审核编辑 > 结构化 > 原始）
                final_content = doc.content
                reviews = await review_controller.get_by_document(doc_id)
                if reviews and reviews[0].edited_content:
                    final_content = reviews[0].edited_content
                else:
                    structured = await StructuredResult.filter(document_id=doc_id).first()
                    if structured:
                        final_content = structured.structured_content

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

    async def _vectorize_from_pages(self, doc: Document, kb: KnowledgeBase):
        """从 DocumentPage 表读取每页内容进行向量化（优先使用编辑后内容）"""
        from llama_index.core.ingestion import IngestionPipeline
        from llama_index.core.node_parser import MarkdownNodeParser
        from llama_index.core.schema import Document as LlamaDocument

        pages = await DocumentPage.filter(document_id=doc.id).order_by("page_number").all()
        if not pages:
            raise ValueError("分页文档没有页面记录")

        embedding_config = await LLMProviderConfig.get(id=kb.embedding_model_id)
        from app.services.llm_builder import build_embed_model
        embed_model = build_embed_model(embedding_config)

        meta = doc.source_meta or {}
        llama_docs = []
        for page in pages:
            # 优先使用编辑后内容，其次原始内容
            page_content = page.content or ""
            if not page_content.strip():
                continue
            page_metadata = {
                "title": doc.title,
                "source_type": doc.source_type,
                "knowledge_base_id": str(kb.id),
                "doc_id": str(doc.id),
                "page_id":page.id,
                "file_type": meta.get("file_type", "unknown"),
                "page_number": page.page_number,
                "total_pages": page.total_pages,
                "doc_type_code": doc.doc_type_code,
            }
            llama_docs.append(
                LlamaDocument(
                    text=page_content,
                    metadata=page_metadata,
                    doc_id=f"{doc.id}",
                )
            )

        if not llama_docs:
            raise ValueError("文档解析后没有有效页面内容")

        node_parser = MarkdownNodeParser()
        pipeline = IngestionPipeline(
            transformations=[node_parser, embed_model],
            vector_store=rag_service._vector_store,
        )
        await pipeline.arun(documents=llama_docs)
        logger.info(f"Paged document vectorized from pages: doc_id={doc.id}, pages={len(llama_docs)}")

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
