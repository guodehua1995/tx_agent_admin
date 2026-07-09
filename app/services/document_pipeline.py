"""文档处理流水线

文档状态机编排器：提取 → 审核 → 切片 → 向量化。
所有文档状态转换的唯一入口，外部调用方只需提交任务，不关心内部状态流转。
"""

import asyncio
import json
import time

from app.controllers.ai_config import ai_config_controller
from app.controllers.review import review_controller
from app.core.redis_lock import LockKey, RedisLock
from app.models.enums import DocumentStatus, DocumentTypeCode, FeishuPublishStatus, ReviewAction
from app.models.rag import (
    Document,
    DocumentPage,
    KnowledgeBase,
    LLMProviderConfig,
    SlicingResult,
)
from app.models.contract import Contract, ContractClause, ContractType
from app.models.quotation import Client
from app.schemas.vector_metadata import ContractMetadata, PagedDocumentMetadata
from app.services.agent_service import agent_service  # noqa: F401
from app.services.chunk_service import chunk_service
from app.services.extraction import run_extraction
from app.services.feishu_service import feishu_service
from app.services.rag_service import rag_service
from app.services.slicing import SLICING_HANDLERS, run_slicing
from app.settings import settings
from app.models.rag import DocumentSourceType

from app.log import logger

# ============================================================
# 全局文档处理 Redis 锁：确保同时只有一个文档在执行 extract() 或 vectorize()
# 使用 Redis 分布式锁，跨 uvicorn worker 进程互斥
# 避免 OCR / 切片 LLM / Embedding 并发请求导致 Timeout
# ============================================================
_EXTRACT_LOCK_KEY = "tx_agent:lock:extract_global"
_VECTIMIZE_LOCK_KEY = "tx_agent:lock:vectorize_global"
_GLOBAL_LOCK_TTL = 600  # 锁过期时间（秒），防止死锁
_GLOBAL_LOCK_POLL_INTERVAL = 1.0  # 等待锁时轮询间隔（秒）


def resolve_document_url(doc: Document) -> str | None:
    """从 Document.source_meta 中解析外部访问链接。

    - feishu_doc: 取 source_meta.feishu_url
    - web_url: 取 source_meta.url
    - file_upload: 无外部链接，返回 None
    """
    meta = doc.source_meta or {}
    source_type = doc.source_type
    if source_type == DocumentSourceType.FEISHU_DOC:
        return meta.get("feishu_url") or None
    if source_type == DocumentSourceType.WEB_URL:
        return meta.get("url") or None
    return None


def _split_clause_content(text: str, max_chars: int = 500) -> list[str]:
    """将条款内容按段落切分为多个子chunk，用于大条款的向量化。

    切分规则：
    - 优先按空行（段落）切分，尽量保持段落完整
    - 单个段落超过 max_chars 时，再按 max_chars 硬切
    - 最后一个 chunk 可能小于 max_chars
    """
    paragraphs = [p.strip() for p in text.split("\n\n") if p.strip()]
    if not paragraphs:
        return [text]

    chunks: list[str] = []
    current = ""
    for p in paragraphs:
        # 单个段落超过上限：先结束当前 chunk，再把该段落按长度硬切
        if len(p) > max_chars:
            if current:
                chunks.append(current)
                current = ""
            for i in range(0, len(p), max_chars):
                chunks.append(p[i : i + max_chars])
            continue

        # 当前 chunk 加上该段落会超限，先结束当前 chunk
        if current and len(current) + len(p) + 2 > max_chars:
            chunks.append(current)
            current = p
        else:
            current = current + "\n\n" + p if current else p

    if current:
        chunks.append(current)

    return chunks


class DocumentPipeline:
    """文档处理状态机编排器。

    所有文档状态转换的唯一入口。外部调用方只需提交任务，不关心内部状态流转。

    对外接口：
        extract(doc_id)           → PENDING_REVIEW | FAILED
        approve(doc_id, reviewer) → COMPLETED | FAILED
        reject(doc_id, reviewer, comment) → REJECTED
        retry(doc_id)             → 自动回到对应阶段
        resubmit(doc_id, content) → PENDING_REVIEW
        vectorize(doc_id)         → COMPLETED | FAILED (补偿任务专用)
    """

    _EXTRACT_LOCK_TTL = 1800
    _VECTORIZE_LOCK_TTL = 1800

    # ==================== 公共接口 ====================

    async def extract(self, doc_id: int) -> None:
        """提取文档内容 → PENDING_REVIEW

        入口状态: PENDING_EXTRACT | FAILED | REJECTED
        出口状态: PENDING_REVIEW | FAILED

        通过 Redis 分布式锁确保跨 worker 同时只有一个文档在执行提取，
        避免 OCR 服务并发请求导致 Timeout。
        """
        from app.core.redis import get_redis

        redis = get_redis()
        global_token = None

        # 阻塞等待获取全局提取锁
        try:
            while True:
                global_token = await redis.set(
                    _EXTRACT_LOCK_KEY, "1", nx=True, ex=_GLOBAL_LOCK_TTL
                )
                if global_token:
                    break
                logger.debug(f"[Extract] doc_id={doc_id} 等待全局提取锁...")
                await asyncio.sleep(_GLOBAL_LOCK_POLL_INTERVAL)

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
                    doc.content = result.content
                    if result.source_meta_patch:
                        doc.source_meta = {**(doc.source_meta or {}), **result.source_meta_patch}
                    doc.status = DocumentStatus.EXTRACTED
                    await doc.save()
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
        finally:
            if global_token:
                await redis.delete(_EXTRACT_LOCK_KEY)

    async def approve(self, doc_id: int, reviewer_id: int | None = None) -> None:
        """审核通过 → APPROVED

        reviewer_id=None 表示系统自动通过，不创建 Review 记录。
        仅变更状态，向量化由 compensate_approved 定时任务统一串行执行。
        """
        doc = await Document.get(id=doc_id)
        if doc.status != DocumentStatus.PENDING_REVIEW:
            raise ValueError(f"文档状态不正确: 期望 PENDING_REVIEW，当前 {doc.status}")

        if reviewer_id is not None:
            await review_controller.create({
                "document_id": doc_id,
                "reviewer_id": reviewer_id,
                "action": ReviewAction.APPROVE,
                "comment": "",
            })

        doc.status = DocumentStatus.APPROVED
        await doc.save()
        logger.info(f"Document approved: id={doc_id}, reviewer_id={reviewer_id}")

    async def reject(self, doc_id: int, reviewer_id: int, comment: str) -> None:
        """驳回 → REJECTED"""
        doc = await Document.get(id=doc_id)
        if doc.status != DocumentStatus.PENDING_REVIEW:
            raise ValueError(f"文档状态不正确: 期望 PENDING_REVIEW，当前 {doc.status}")

        await review_controller.create({
            "document_id": doc_id,
            "reviewer_id": reviewer_id,
            "action": ReviewAction.REJECT,
            "comment": comment,
        })

        doc.status = DocumentStatus.REJECTED
        await doc.save()
        logger.info(f"Document rejected: id={doc_id}, reviewer_id={reviewer_id}")

    async def retry(self, doc_id: int) -> None:
        """重试失败/驳回文档，自动判断回到哪个阶段。

        - 有 content 的 FAILED → 设为 APPROVED，由 compensate_approved 统一向量化
        - 无 content / REJECTED → 设为 PENDING_EXTRACT，由 compensate_pending_extract 统一提取
        """
        doc = await Document.get(id=doc_id)
        if doc.status not in (DocumentStatus.FAILED, DocumentStatus.REJECTED):
            raise ValueError(f"只能重试 FAILED 或 REJECTED 状态的文档，当前 {doc.status}")

        if doc.content and doc.status == DocumentStatus.FAILED:
            logger.info(f"Document retry → approved (vectorize by compensate): id={doc_id}")
            doc.status = DocumentStatus.APPROVED
            await doc.save()
        else:
            logger.info(f"Document retry → pending_extract: id={doc_id}")
            doc.status = DocumentStatus.PENDING_EXTRACT
            await doc.save()

    async def resubmit(self, doc_id: int, content: str) -> None:
        """编辑内容后重新提审 → PENDING_REVIEW"""
        doc = await Document.get(id=doc_id)
        if doc.status != DocumentStatus.REJECTED:
            raise ValueError(f"只有 REJECTED 状态的文档才能编辑内容，当前 {doc.status}")

        doc.content = content
        doc.status = DocumentStatus.PENDING_REVIEW
        await doc.save()
        logger.info(f"Document content updated and resubmitted: id={doc_id}")

    async def vectorize(self, doc_id: int) -> None:
        """切片（如需要）→ 向量化入库 → COMPLETED

        通过 Redis 分布式锁确保跨 worker 同时只有一个文档在执行向量化/切片，
        避免 LLM / Embedding 并发请求导致超时。
        """
        from app.core.redis import get_redis

        redis = get_redis()
        global_token = None

        # 阻塞等待获取全局向量化锁
        try:
            while True:
                global_token = await redis.set(
                    _VECTIMIZE_LOCK_KEY, "1", nx=True, ex=_GLOBAL_LOCK_TTL
                )
                if global_token:
                    break
                logger.debug(f"[Vectorize] doc_id={doc_id} 等待全局向量化锁...")
                await asyncio.sleep(_GLOBAL_LOCK_POLL_INTERVAL)

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
                    await chunk_service.delete_by_doc_id(doc_id)

                    if doc.doc_type_code == DocumentTypeCode.CONTRACT:
                        await self._finalize_content_from_review(doc)
                        if doc.doc_type_code in SLICING_HANDLERS:
                            doc.status = DocumentStatus.SLICING
                            await doc.save()
                            await self._run_slicing(doc)
                        doc.status = DocumentStatus.VECTORIZING
                        await doc.save()
                        await self._vectorize_contract(doc, kb)
                    elif DocumentTypeCode.is_paged_type(doc.doc_type_code):
                        doc.status = DocumentStatus.VECTORIZING
                        await doc.save()
                        await self._vectorize_from_pages(doc, kb)
                    else:
                        doc.status = DocumentStatus.VECTORIZING
                        await doc.save()
                        final_content = doc.content
                        slicing = await SlicingResult.filter(document_id=doc_id).first()
                        if slicing:
                            final_content = slicing.sliced_content
                        metadata = {"title": doc.title, "source_type": doc.source_type, "doc_type_code": doc.doc_type_code}
                        await rag_service.ingest_document(
                            doc_id=str(doc.id), content=final_content, kb=kb, metadata=metadata,
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
        finally:
            if global_token:
                await redis.delete(_VECTIMIZE_LOCK_KEY)

    # ==================== 内部帮助方法 ====================

    async def _get_feishu_access_token(self) -> str:
        return await feishu_service.get_tenant_access_token(
            settings.FEISHU_DOC_BOT_APPID, settings.FEISHU_DOC_BOT_APPSECRET
        )

    async def _finalize_content_from_review(self, doc: Document):
        pages = await DocumentPage.filter(document_id=doc.id).order_by("page_number").all()
        if pages:
            merged = "\n\n".join((p.content or "").strip() for p in pages if (p.content or "").strip())
            if merged:
                doc.content = merged
                await doc.save()

    async def _run_slicing(self, doc: Document):
        existing = await SlicingResult.filter(document_id=doc.id).first()
        if existing:
            logger.info(f"Slicing already exists for doc_id={doc.id}, skipping")
            return

        chat_models = await ai_config_controller.get_active_chat_models()
        if not chat_models:
            raise ValueError("没有可用的 Chat 模型配置")
        model_config = chat_models[0]

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

    async def _vectorize_from_pages(self, doc: Document, kb: KnowledgeBase):
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
                title=doc.title, source_type=doc.source_type,
                knowledge_base_id=str(kb.id), source_doc_id=str(doc.id),
                doc_type_code=doc.doc_type_code, file_type=meta.get("file_type", "unknown"),
                page_id=page.id, page_number=page.page_number,
                total_pages=page.total_pages, screenshot_url=page.screenshot_url,
            )
            llama_docs.append(LlamaDocument(
                text=page_content, metadata=page_metadata.to_dict(), doc_id=f"{doc.id}",
            ))

        if not llama_docs:
            raise ValueError("文档解析后没有有效页面内容")

        node_parser = MarkdownNodeParser()
        pipeline = IngestionPipeline(
            transformations=[node_parser, embed_model],
            vector_store=rag_service._vector_store,
        )
        await pipeline.arun(documents=llama_docs)
        logger.info(f"Paged document vectorized: doc_id={doc.id}, pages={len(llama_docs)}")

    async def _vectorize_contract(self, doc: Document, kb: KnowledgeBase):
        from llama_index.core.ingestion import IngestionPipeline
        from llama_index.core.schema import Document as LlamaDocument
        from app.services.llm_builder import build_embed_model

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

        summary_clause = next((c for c in clauses if int(c.get("clause_index", -1)) == 0), None)
        if summary_clause:
            summary_text = (summary_clause.get("content") or "").strip()
            if summary_text:
                doc.summary = summary_text
                await doc.save(update_fields=["summary"])

        embedding_config = await LLMProviderConfig.get(id=kb.embedding_model_id)
        embed_model = build_embed_model(embedding_config)

        llama_docs = []
        chunk_count = 0

        # 构建条款树：按倒数第二层级合并子条款内容为 chunk
        max_level = max(
            (len([p for p in (c.get("clause_title") or "").split("-") if p.strip()]) - 1)
            for c in clauses
            if c.get("clause_title")
        )
        target_level = max(0, max_level - 1)

        # 建立父子关系：parent_path -> list of child clauses
        children_map: dict[str, list] = {}
        for clause in clauses:
            title = clause.get("clause_title") or ""
            parts = [p.strip() for p in title.split("-") if p.strip()]
            if len(parts) > 1:
                parent_path = "-".join(parts[:-1])
                children_map.setdefault(parent_path, []).append(clause)

        def _collect_descendant_content(clause_title: str, collected: set) -> str:
            """递归收集所有子条款内容"""
            if clause_title in collected:
                return ""
            collected.add(clause_title)
            parts: list[str] = []
            for child in children_map.get(clause_title, []):
                child_content = (child.get("content") or "").strip()
                if child_content:
                    parts.append(child_content)
                child_title = child.get("clause_title") or ""
                if child_title:
                    grand = _collect_descendant_content(child_title, collected)
                    if grand:
                        parts.append(grand)
            return "\n\n".join(parts)

        for clause in clauses:
            title = clause.get("clause_title") or ""
            content = (clause.get("content") or "").strip()
            parts = [p.strip() for p in title.split("-") if p.strip()]
            level = len(parts) - 1 if parts else 0

            # 跳过比 target_level 更深的层级（会被父级合并）
            if level > target_level:
                continue

            # 跳过高于 target_level 且有子条款的层级（子条款会在 target_level 处理）
            if level < target_level and title and title in children_map:
                continue

            # 合并自身内容 + 所有子条款内容（仅 target_level 需要收集子孙）
            combined = content
            if title and level == target_level:
                descendant_content = _collect_descendant_content(title, set())
                if descendant_content:
                    combined = f"{combined}\n\n{descendant_content}" if combined else descendant_content

            if not combined.strip():
                continue

            # 大条款内部子切分：每个子chunk共享同一条款的 clause_index / clause_title
            sub_chunks = _split_clause_content(combined.strip(), max_chars=500)
            for sub_text in sub_chunks:
                header = (
                    f"[合同: {doc.title} | "
                    f"甲方: {meta.get('party_a', '')} | "
                    f"乙方: {meta.get('party_b', '')} | "
                    f"类型: {meta.get('contract_type', '')}] | "
                    f"条款 {clause['clause_title']}"
                )
                text = f"{header}\n{sub_text}"
                clause_meta = ContractMetadata(
                    title=doc.title, source_type=doc.source_type,
                    knowledge_base_id=str(kb.id), source_doc_id=str(doc.id),
                    doc_type_code=doc.doc_type_code,
                    party_a=meta.get("party_a", "") or "",
                    party_b=meta.get("party_b", "") or "",
                    contract_type=meta.get("contract_type", "其他"),
                    clause_index=int(clause["clause_index"]),
                    clause_title=clause.get("clause_title"),
                )
                llama_docs.append(LlamaDocument(
                    text=text, metadata=clause_meta.to_dict(),
                ))
                chunk_count += 1

        if not llama_docs:
            raise ValueError("合同解析后无有效条款")

        pipeline = IngestionPipeline(
            transformations=[embed_model],
            vector_store=rag_service._vector_store,
        )
        await pipeline.arun(documents=llama_docs)
        logger.info(f"Contract vectorized: doc_id={doc.id}, chunks={chunk_count}, clauses={len(clauses)}")

        # 保存到 Contract / ContractClause 表
        await self._save_contract_from_slicing(doc, meta, clauses)

    async def _save_contract_from_slicing(
        self, doc: Document, meta: dict, clauses: list[dict],
    ):
        """从切片结果保存 Contract + ContractClause 记录"""
        # 检查是否已存在
        existing = await Contract.filter(document_id=doc.id, is_deleted=False).first()
        if existing:
            logger.info(f"Contract already exists for doc_id={doc.id}, skipping save")
            return

        # 匹配/创建 Client
        party_a_id = await self._get_or_create_client(meta.get("party_a", ""))
        party_b_id = await self._get_or_create_client(meta.get("party_b", ""))

        # 匹配/创建 ContractType
        contract_type_name = meta.get("contract_type", "其他")
        contract_type = await ContractType.filter(
            name=contract_type_name, is_deleted=False,
        ).first()
        if not contract_type:
            contract_type = await ContractType.filter(code="other", is_deleted=False).first()

        # 创建 Contract
        document_url = resolve_document_url(doc)
        # meta 中空字符串需转 None，兼容 Tortoise DatetimeField/DecimalField
        signing_date = meta.get("signing_date") or None
        expiry_date = meta.get("expiry_date") or None
        total_amount = meta.get("total_amount") or None
        contract = await Contract.create(
            document_id=doc.id,
            contract_type_id=contract_type.id if contract_type else None,
            party_a_client_id=party_a_id or 0,
            party_b_client_id=party_b_id,
            project_name=doc.title,
            summary=doc.summary,
            document_url=document_url,
            signing_date=signing_date,
            expiry_date=expiry_date,
            total_amount=total_amount,
            clause_count=0,
        )

        # 创建 ContractClause 树
        parent_map: dict[str, int] = {}
        clause_count = 0
        for clause in clauses:
            clause_index = clause.get("clause_index", 0)
            clause_title = clause.get("clause_title") or ""
            original_text = clause.get("content") or ""

            # 解析层级
            parts = [p.strip() for p in clause_title.split("-") if p.strip()]
            level = len(parts) - 1 if parts else 0

            # 确定 parent：如果中间层级缺失，自动创建占位 clause
            parent_id = None
            if level > 0 and len(parts) > 1:
                parent_id = await self._ensure_parent_chain(
                    contract, clause_title, parent_map,
                )

            # 概要 clause 的 summary
            summary = None
            if clause_index == 0:
                summary = original_text[:500] if original_text else None

            clause_obj = await ContractClause.create(
                contract=contract,
                parent_id=parent_id,
                clause_index=clause_index,
                clause_title=clause_title if clause_title else None,
                clause_level=level,
                original_text=original_text,
                summary=summary,
                sort_order=clause_index,
            )

            full_path = "-".join(parts) if parts else str(clause_index)
            parent_map[full_path] = clause_obj.id
            clause_count += 1

        # 更新条款计数
        contract.clause_count = clause_count
        await contract.save(update_fields=["clause_count"])

        logger.info(
            f"Contract saved: doc_id={doc.id}, contract_id={contract.id}, clauses={clause_count}"
        )

    async def _ensure_parent_chain(
        self,
        contract: Contract,
        clause_title: str,
        parent_map: dict[str, int],
    ) -> int | None:
        """确保中间层级父条款存在，缺失时自动创建占位 clause。

        场景：LLM 跳过了"太粗"的中间层级（如只输出"合作范围-服务内容-软件开发"，
        跳过了"合作范围"和"合作范围-服务内容"），导致 parent_map 中找不到父级。
        此方法逐级检查并创建占位 clause，保证树结构完整。
        """
        parts = [p.strip() for p in clause_title.split("-") if p.strip()]
        if len(parts) <= 1:
            return None

        current_parent_id = None
        for i in range(len(parts) - 1):
            prefix = "-".join(parts[: i + 1])
            if prefix in parent_map:
                current_parent_id = parent_map[prefix]
            else:
                level = i
                # 占位 clause 使用负数 clause_index，避免与真实条款冲突
                placeholder_index = -(len(parent_map) + 1)
                placeholder = await ContractClause.create(
                    contract=contract,
                    parent_id=current_parent_id,
                    clause_index=placeholder_index,
                    clause_title=prefix,
                    clause_level=level,
                    original_text="",
                    sort_order=placeholder_index,
                )
                parent_map[prefix] = placeholder.id
                current_parent_id = placeholder.id
                logger.debug(
                    f"[pipeline] Created placeholder clause: title={prefix}, level={level}"
                )

        return current_parent_id

    async def _get_or_create_client(self, name: str) -> int | None:
        """根据名称匹配或创建 Client"""
        if not name or not name.strip():
            return None
        name = name.strip()
        client = await Client.filter(name=name, is_deleted=False).first()
        if client:
            return client.id
        client = await Client.filter(short_name=name, is_deleted=False).first()
        if client:
            return client.id
        # 未匹配：创建占位
        client = await Client.create(
            name=name, short_name=name, client_type="企业", is_active=True,
        )
        logger.info(f"[pipeline] Created placeholder Client: id={client.id}, name={name}")
        return client.id

    async def publish_to_feishu(self, slicing_result_id: int):
        from app.controllers.feishu_bot import feishu_bot_controller

        result = await SlicingResult.get(id=slicing_result_id)
        doc = await Document.get(id=result.document_id)

        try:
            result.feishu_publish_status = FeishuPublishStatus.PUBLISHING
            await result.save()

            bot_configs = await feishu_bot_controller.model.filter(is_active=True).first()
            if not bot_configs:
                raise ValueError("没有可用的飞书机器人配置")

            access_token = await feishu_service.get_tenant_access_token(
                bot_configs.app_id, bot_configs.app_secret
            )
            url = await feishu_service.create_doc_in_folder(
                folder_token=settings.FEISHU_STRUCTURED_FOLDER_TOKEN,
                title=doc.title, content=result.sliced_content, access_token=access_token,
            )

            result.feishu_publish_status = FeishuPublishStatus.PUBLISHED
            result.feishu_publish_url = url
            await result.save()
            logger.info(f"Published to Feishu: result_id={slicing_result_id}, url={url}")

        except Exception:
            result.feishu_publish_status = FeishuPublishStatus.FAILED
            await result.save()
            logger.exception(f"Feishu publish failed: result_id={slicing_result_id}")


document_pipeline = DocumentPipeline()