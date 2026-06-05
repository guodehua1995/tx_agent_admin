import json
import time

from app.controllers.ai_config import ai_config_controller
from app.controllers.conversation import conversation_controller
from app.controllers.feishu_bot import feishu_bot_controller
from app.core.redis_lock import LockKey, RedisLock
from app.models.admin import User
from app.models.enums import DocumentStatus, DocumentTypeCode, FeishuPublishStatus
from app.models.rag import (
    Agent,
    ChatMessage,
    Document,
    DocumentPage,
    KnowledgeBase,
    LLMProviderConfig,
    SlicingResult,
)
from app.schemas.vector_metadata import ContractMetadata, PagedDocumentMetadata
from app.services.agent_service import agent_service  # noqa: F401  保持 agent 注册
from app.services.extraction import run_extraction
from app.services.extraction.base import BaseExtractor
from app.services.feishu_service import feishu_service
from app.services.rag_service import rag_service
from app.services.chunk_service import chunk_service
from app.services.slicing import SLICING_HANDLERS, run_slicing
from app.settings import settings

from app.log import logger


class DocumentPipeline:
    """文档处理流程编排：提取 → 待审核 → 切片 → 向量化"""

    # ==================== 阶段一：提取 ====================

    # 单文档提取最长允许时间（秒）。PDF 多页 vision 提取较慢，给足余量。
    _EXTRACT_LOCK_TTL = 1800

    # 单文档向量化最长允许时间（秒）。合同切片 + 批量 embedding 可能十几分钟。
    _VECTORIZE_LOCK_TTL = 1800

    async def process_document(self, doc_id: int):
        """文档上传后：调提取层（按 doc_type_code 路由）→ 落 doc.content → 进入待审核

        通过 Redis 分布式锁保证同一文档同一时刻只有一个提取任务在跑，
        避免 HTTP 触发与 scheduler 补偿任务并发执行同一文档。
        """
        lock = RedisLock()
        lock_key = f"{LockKey.DOCUMENT_PROCESS}:{doc_id}"
        token = await lock.acquire(lock_key, ttl=self._EXTRACT_LOCK_TTL)
        if not token:
            logger.info(f"Document extraction skipped (already in progress): id={doc_id}")
            return

        try:
            doc = await Document.get(id=doc_id)
            try:
                result = await run_extraction(doc)

                # 回写 content + 增量 source_meta
                doc.content = result.content
                if result.source_meta_patch:
                    doc.source_meta = {**(doc.source_meta or {}), **result.source_meta_patch}

                doc.status = DocumentStatus.EXTRACTED
                await doc.save()

                # EXTRACTED 是瞬态，立刻进入待审核
                doc.status = DocumentStatus.PENDING_REVIEW
                await doc.save()
                logger.info(f"Document extracted: id={doc_id}, status=pending_review")

            except Exception as e:
                doc.status = DocumentStatus.FAILED
                doc.error_message = str(e)
                await doc.save()
                logger.exception(f"Document extraction failed: id={doc_id}")
        finally:
            await lock.release(lock_key, token)

    # ==================== 阶段二：审核后：切片 + 向量化 ====================

    async def _get_feishu_access_token(self) -> str:
        """获取飞书拉取机器人的 access_token 和 bot_config"""
        # 
        access_token = await feishu_service.get_tenant_access_token(settings.FEISHU_DOC_BOT_APPID, settings.FEISHU_DOC_BOT_APPSECRET)
        return access_token

    async def _fetch_feishu_content(self, doc: Document) -> str:
        """从飞书拉取文档内容（根据解析出的 doc_type 路由）"""
        meta = doc.source_meta or {}
        feishu_url = meta.get("feishu_url", "")
        doc_token, doc_type = feishu_service.parse_feishu_url(feishu_url)

        access_token = await self._get_feishu_access_token()

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
            await BaseExtractor._save_page_records(doc, pages)
            markdown_content = document_converter.pages_to_markdown(pages)
           
            doc_token, doc_type = feishu_service.parse_feishu_url(file_path)
            doc.source_meta = {**meta,"feishu_doc_token": doc_token, "feishu_doc_type": doc_type, "file_type": ext, "page_count": len(pages)}
            return markdown_content

        # 其他类型尝试作为纯文本读取
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
        """审核通过后: 切片（如需要）→ 向量化入库

        通过 Redis 分布式锁保证同一文档同一时刻只有一个向量化任务在跑，
        避免 HTTP 触发与 scheduler 补偿任务并发导致重复入库。
        """
        lock = RedisLock()
        lock_key = f"{LockKey.DOCUMENT_VECTORIZE}:{doc_id}"
        token = await lock.acquire(lock_key, ttl=self._VECTORIZE_LOCK_TTL)
        if not token:
            logger.info(f"Document vectorization skipped (already in progress): id={doc_id}")
            return

        try:
            doc = await Document.get(id=doc_id)
            logger.info(f"Vectorizing document: id={doc_id}, name={doc.title}")
            try:
                kb = await KnowledgeBase.get(id=doc.knowledge_base_id)

                # 先清理旧向量数据（重试场景下防止重复入库）
                await chunk_service.delete_by_doc_id(doc_id)
                logger.info(f"Cleaned up existing vectors before vectorize: doc_id={doc_id}")

                # 合同类文档：使用审核后的最终原文 → 切片 → 逐条款入库
                if doc.doc_type_code == DocumentTypeCode.CONTRACT:
                    await self._finalize_content_from_review(doc)
                    if doc.doc_type_code in SLICING_HANDLERS:
                        doc.status = DocumentStatus.SLICING
                        await doc.save()
                        await self._run_slicing(doc)
                    doc.status = DocumentStatus.VECTORIZING
                    await doc.save()
                    await self._vectorize_contract(doc, kb)
                # 分页类型文档：从 DocumentPage 表逐页读取内容向量化
                elif DocumentTypeCode.is_paged_type(doc.doc_type_code):
                    doc.status = DocumentStatus.VECTORIZING
                    await doc.save()
                    await self._vectorize_from_pages(doc, kb)
                else:
                    # 非分页文档：优先使用切片产物，否则原始内容
                    doc.status = DocumentStatus.VECTORIZING
                    await doc.save()
                    final_content = doc.content
                    slicing = await SlicingResult.filter(document_id=doc_id).first()
                    if slicing:
                        final_content = slicing.sliced_content

                    metadata = {"title": doc.title, "source_type": doc.source_type, "doc_type_code": doc.doc_type_code}
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
        finally:
            await lock.release(lock_key, token)

    async def _finalize_content_from_review(self, doc: Document):
        """审核通过后拼出最终原文并回写 doc.content。"""
        pages = await DocumentPage.filter(document_id=doc.id).order_by("page_number").all()
        if pages:
            merged = "\n\n".join((p.content or "").strip() for p in pages if (p.content or "").strip())
            if merged:
                doc.content = merged
                await doc.save()

    async def _run_slicing(self, doc: Document):
        """执行切片处理（按 doc_type_code 路由到 SLICING_HANDLERS）

        如果已存在切片结果（重试场景），直接复用，不重复切片。
        """
        # 重试场景：切片已完成，直接跳过
        existing = await SlicingResult.filter(document_id=doc.id).first()
        if existing:
            logger.info(f"Slicing already exists for doc_id={doc.id}, skipping")
            return

        chat_models = await ai_config_controller.get_active_chat_models()
        if not chat_models:
            raise ValueError("没有可用的 Chat 模型配置")
        model_config = chat_models[0]

        # 合同等需要分页元信息的处理器会从 DocumentPage 读取页面列表
        pages = await DocumentPage.filter(document_id=doc.id).order_by("page_number").all()
        pages_arg = list(pages) if pages else None

        start_time = time.time()
        result = await run_slicing(doc.doc_type_code, doc.content, model_config, pages=pages_arg)
        elapsed_ms = int((time.time() - start_time) * 1000)

        await SlicingResult.create(
            document_id=doc.id,
            sliced_content=result.content,
            slicing_model_id=model_config.id,
            prompt_used=result.prompt_used,
            token_usage=result.token_usage,
            processing_time_ms=elapsed_ms,
        )

    # ==================== 向量化各类型分支 ====================

    async def _vectorize_from_pages(self, doc: Document, kb: KnowledgeBase):
        """从 DocumentPage 表读取每页内容进行向量化"""
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
            page_content = page.content or ""
            if not page_content.strip():
                continue
            page_metadata = PagedDocumentMetadata(
                title=doc.title,
                source_type=doc.source_type,
                knowledge_base_id=str(kb.id),
                source_doc_id=str(doc.id),
                doc_type_code=doc.doc_type_code,
                file_type=meta.get("file_type", "unknown"),
                page_id=page.id,
                page_number=page.page_number,
                total_pages=page.total_pages,
                screenshot_url=page.screenshot_url,
            )
            llama_docs.append(
                LlamaDocument(
                    text=page_content,
                    metadata=page_metadata.to_dict(),
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

    async def _vectorize_contract(self, doc: Document, kb: KnowledgeBase):
        """合同文档向量化：解析 SlicingResult.sliced_content → 逐条款入库"""
        from llama_index.core.ingestion import IngestionPipeline
        from llama_index.core.schema import Document as LlamaDocument

        from app.services.llm_builder import build_embed_model

        # 读取本次切片产出
        slicing_json = None
        slicing = await SlicingResult.filter(document_id=doc.id).first()
        if slicing:
            slicing_json = slicing.sliced_content

        if not slicing_json:
            raise ValueError("合同文档缺少切片内容，请先完成审核")

        try:
            data = json.loads(slicing_json)
        except json.JSONDecodeError as e:
            raise ValueError(f"合同切片内容不是合法 JSON: {e}")

        meta = data.get("meta") or {}
        clauses = data.get("clauses") or []
        if not clauses:
            raise ValueError("合同解析后无有效条款")

        # 将 clause_index=0（概要）同步写入 Document.summary
        summary_clause = next((c for c in clauses if int(c.get("clause_index", -1)) == 0), None)
        if summary_clause:
            summary_text = (summary_clause.get("content") or "").strip()
            if summary_text:
                doc.summary = summary_text
                await doc.save(update_fields=["summary"])
                logger.info(f"Document summary synced from clause_0: doc_id={doc.id}")

        embedding_config = await LLMProviderConfig.get(id=kb.embedding_model_id)
        embed_model = build_embed_model(embedding_config)

        llama_docs = []
        for clause in clauses:
            content = (clause.get("content") or "").strip()
            if not content:
                continue

            # 构建 text 头部，使条款脱离合同也能在检索中被识别
            header = (
                f"[合同: {doc.title} | "
                f"甲方: {meta.get('party_a', '')} | "
                f"乙方: {meta.get('party_b', '')} | "
                f"类型: {meta.get('contract_type', '')}] | "
                f"条款 {clause['clause_title']}"
            )
            text = f"{header}\n{content}"

            clause_meta = ContractMetadata(
                title=doc.title,
                source_type=doc.source_type,
                knowledge_base_id=str(kb.id),
                source_doc_id=str(doc.id),
                doc_type_code=doc.doc_type_code,
                party_a=meta.get("party_a", "") or "",
                party_b=meta.get("party_b", "") or "",
                contract_type=meta.get("contract_type", "其他"),
                clause_index=int(clause["clause_index"]),
                clause_title=clause.get("clause_title"),
            )
            llama_docs.append(
                LlamaDocument(
                    text=text,
                    metadata=clause_meta.to_dict(),
                    doc_id=f"contract_{doc.id}_clause_{clause['clause_index']}",
                )
            )

        if not llama_docs:
            raise ValueError("合同解析后无有效条款")

        # 合同已按条款切好，直接 embed，不走 NodeParser
        pipeline = IngestionPipeline(
            transformations=[embed_model],
            vector_store=rag_service._vector_store,
        )
        await pipeline.arun(documents=llama_docs)
        logger.info(f"Contract vectorized: doc_id={doc.id}, clauses={len(llama_docs)}")

    # ==================== 飞书发布 ====================

    async def publish_to_feishu(self, slicing_result_id: int):
        """将切片结果发布到飞书云文档"""
        result = await SlicingResult.get(id=slicing_result_id)
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
                content=result.sliced_content,
                access_token=access_token,
            )

            result.feishu_publish_status = FeishuPublishStatus.PUBLISHED
            result.feishu_publish_url = url
            await result.save()
            logger.info(f"Published to Feishu: result_id={slicing_result_id}, url={url}")

        except Exception:
            result.feishu_publish_status = FeishuPublishStatus.FAILED
            await result.save()
            logger.exception(f"Feishu publish failed: result_id={slicing_result_id}")

    # ==================== 飞书机器人对话 ====================

    async def handle_bot_message(self, bot_id: int, feishu_open_id: str, chat_id: str, question: str) -> dict:
        """飞书机器人消息处理"""
        # 1. bot_config → agent → knowledge_bases
        bot = await feishu_bot_controller.get(id=bot_id)
        if not bot.agent_id:
            return {"answer": "该机器人尚未绑定 Agent，请联系管理员配置", "sources": []}
        agent = await Agent.get(id=bot.agent_id)
        knowledge_bases = await agent.knowledge_bases.all()
        if not knowledge_bases:
            return {"answer": "该 Agent 未关联任何知识库", "sources": []}

        logger.debug("bot get knowledge bases")

        # 2. feishu_open_id → user
        user = await User.filter(feishu_open_id=feishu_open_id).first()
        if not user:
            return {"answer": "您的账号尚未注册，请联系管理员开通后使用", "sources": []}
        logger.debug("bot get user")
        # 3. 获取/创建 conversation
        conv = await conversation_controller.get_or_create(agent_id=agent.id, user_id=user.id)
        logger.debug("bot get conversation")
        # 4. 加载历史消息（agent_friendly=True 自动将工具调用消息转为 assistant 类型）
        history = await conversation_controller.get_messages(
            conv.id, limit=agent.max_history_turns * 2, agent_friendly=True
        )
        logger.debug("bot get history")
        # 5. RAG 问答
        chat_model = await LLMProviderConfig.get(id=agent.chat_model_id)
        logger.debug("bot get chat model")
        start_time = time.time()
        result = await rag_service.chat(
            question=question,
            history=history,
            knowledge_bases=list(knowledge_bases),
            chat_model_config=chat_model,
            system_prompt=agent.system_prompt,
        )
        logger.debug("bot get rag service")
        elapsed_ms = int((time.time() - start_time) * 1000)

        # 6. 保存消息记录
        logger.debug("bot create user message")
        await ChatMessage.create(conversation_id=conv.id, type="user", content=question, feishu_message_id=None)
        for tc in result.get("tool_calls", []):
            await ChatMessage.create(
                conversation_id=conv.id,
                type="tool_call",
                content=json.dumps({"tool_name": tc["tool_name"], "tool_input": tc["tool_input"]}, ensure_ascii=False),
            )
            await ChatMessage.create(
                conversation_id=conv.id,
                type="tool_call_result",
                content=json.dumps({"tool_name": tc["tool_name"], "result": tc["tool_output"]}, ensure_ascii=False),
            )
        
        logger.debug("bot create assistant message")
        await ChatMessage.create(
            conversation_id=conv.id,
            type="assistant",
            content=result["answer"],
            retrieved_chunks=result["sources"],
            response_time_ms=elapsed_ms,
        )

        from datetime import datetime
        tool_msg_count = len(result.get("tool_calls", [])) * 2
        conv.message_count += 2 + tool_msg_count
        conv.last_active_at = datetime.now()
        await conv.save()

        return result


document_pipeline = DocumentPipeline()
