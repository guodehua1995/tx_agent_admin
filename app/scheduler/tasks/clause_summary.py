"""合同条款摘要异步处理定时任务

扫描待摘要条款 → 生成摘要 → 合并合同摘要 → 同步向量 chunks。
"""

import json
from collections import defaultdict

from app.log import logger
from app.models.contract import Contract, ContractClause, ContractType
from app.models.quotation import Client
from app.models.rag import Document
from app.settings import settings


async def process_clause_summaries():
    """扫描待摘要条款并处理。

    1. 扫描 summary_status='pending_summary' 的条款
    2. 逐条生成摘要 → summary_status='summary_complete'
    3. 按 contract_id 分组，无 pending_summary 的合同触发摘要合并
    4. 合并合同摘要 + 新条款摘要 + 待删除摘要 → LLM → 新合同摘要
    5. 同步向量 chunks（合同概要 + 新完成条款）
    6. 清理 pending_delete 条款（最终删除）
    """
    if not settings.SCHEDULER_ENABLED:
        return

    try:
        # 1. 获取 Chat 模型配置
        from app.controllers.ai_config import ai_config_controller
        chat_models = await ai_config_controller.get_active_chat_models()
        if not chat_models:
            logger.warning("[ClauseSummary] no active chat model")
            return
        model_config = chat_models[0]

        from app.services.llm_builder import build_llm
        llm = build_llm(model_config)

        # 2. 扫描待摘要条款
        pending_clauses = await ContractClause.filter(
            summary_status="pending_summary", is_deleted=False,
        ).all()

        if pending_clauses:
            logger.info(f"[ClauseSummary] found {len(pending_clauses)} pending clauses")
            await _summarize_clauses(pending_clauses, llm)

        # 3. 按合同分组，处理无 pending_summary 的合同
        affected_contract_ids = set()
        if pending_clauses:
            affected_contract_ids.update(c.contract_id for c in pending_clauses)

        # 也检查有 pending_delete 但无 pending_summary 的合同
        pending_delete = await ContractClause.filter(
            summary_status="pending_delete", is_deleted=False,
        ).all()
        if pending_delete:
            affected_contract_ids.update(c.contract_id for c in pending_delete)

        if not affected_contract_ids:
            return

        # 4. 对每个合同检查是否还有 pending_summary
        for contract_id in affected_contract_ids:
            still_pending = await ContractClause.filter(
                contract_id=contract_id, summary_status="pending_summary",
                is_deleted=False,
            ).exists()
            if still_pending:
                continue

            has_complete_or_delete = await ContractClause.filter(
                contract_id=contract_id, is_deleted=False,
                summary_status__in=["summary_complete", "pending_delete"],
            ).exists()
            if not has_complete_or_delete:
                continue

            try:
                await _process_contract_summary(contract_id, llm)
            except Exception:
                logger.exception(
                    f"[ClauseSummary] contract summary failed: contract_id={contract_id}",
                )

    except Exception:
        logger.exception("[ClauseSummary] process failed")


async def _summarize_clauses(clauses: list[ContractClause], llm) -> None:
    """逐条生成条款摘要并保存。"""
    from llama_index.core.llms import ChatMessage as LiChatMessage

    CLAUSE_SUMMARY_PROMPT = (
        "你是合同条款解析助手。请用 50~100 字概括以下条款内容，"
        "提取核心约定和关键信息。"
        "如果条款内容是双语的（中英对照），只输出中文部分。"
        "直接输出摘要正文，不要标题和前置说明。"
    )

    for clause in clauses:
        content = (clause.original_text or "")[:2000]
        if not content.strip():
            clause.summary_status = "summary_complete"
            await clause.save(update_fields=["summary_status"])
            continue

        try:
            messages = [
                LiChatMessage(role="system", content=CLAUSE_SUMMARY_PROMPT),
                LiChatMessage(role="user", content=content),
            ]
            resp = await llm.achat(messages)
            summary = (resp.message.content or "").strip()

            if summary:
                clause.summary = summary
            clause.summary_status = "summary_complete"
            await clause.save(update_fields=["summary", "summary_status"])
            logger.info(
                f"[ClauseSummary] clause summarized: id={clause.id}, title={clause.clause_title}"
            )
        except Exception:
            logger.exception(
                f"[ClauseSummary] clause summary failed: id={clause.id}",
            )
            # 失败也标记为 complete，避免阻塞
            clause.summary_status = "summary_complete"
            await clause.save(update_fields=["summary_status"])


async def _process_contract_summary(contract_id: int, llm) -> None:
    """处理单个合同的摘要合并 + 向量同步 + pending_delete 清理。"""
    from llama_index.core.llms import ChatMessage as LiChatMessage

    contract = await Contract.filter(id=contract_id, is_deleted=False).first()
    if not contract:
        return

    # 收集待删除条款的摘要
    pending_delete_clauses = await ContractClause.filter(
        contract_id=contract_id, summary_status="pending_delete",
        is_deleted=False,
    ).all()

    # 收集已完成摘要的条款
    completed_clauses = await ContractClause.filter(
        contract_id=contract_id, summary_status="summary_complete",
        is_deleted=False,
    ).exclude(clause_index=0).order_by("clause_index").all()

    if not completed_clauses and not pending_delete_clauses:
        return

    # 收集新条款摘要（有 summary 且非 pending_delete 的）
    new_summaries = []
    for c in completed_clauses:
        if c.summary:
            new_summaries.append(f"[{c.clause_title or ''}] {c.summary}")

    deleted_summaries = []
    for c in pending_delete_clauses:
        if c.summary:
            deleted_summaries.append(f"[{c.clause_title or ''}] {c.summary}")

    # 合并合同摘要
    existing_summary = contract.summary or ""
    MERGE_PROMPT = (
        "你是合同解析助手。以下是现有合同摘要，以及新增/删除条款的摘要。"
        "请综合这些信息，输出一份更新后的完整合同摘要（200~400字），"
        "保留原有结构，自然融入新增内容，移除已删除条款的影响。"
        "如果合同内容是双语的（中英对照），只输出中文部分。"
        "直接输出概要正文，不要标题和前置说明。"
    )
    merge_input = f"# 现有合同摘要\n{existing_summary}\n\n"
    if new_summaries:
        merge_input += f"# 新增/修改的条款\n" + "\n".join(new_summaries) + "\n\n"
    if deleted_summaries:
        merge_input += f"# 已删除的条款\n" + "\n".join(deleted_summaries)

    try:
        messages = [
            LiChatMessage(role="system", content=MERGE_PROMPT),
            LiChatMessage(role="user", content=merge_input),
        ]
        resp = await llm.achat(messages)
        new_summary = (resp.message.content or "").strip()

        if new_summary:
            contract.summary = new_summary
            await contract.save(update_fields=["summary"])

            doc = await Document.filter(id=contract.document_id).first()
            if doc:
                doc.summary = new_summary
                await doc.save(update_fields=["summary"])

            logger.info(
                f"[ClauseSummary] contract summary merged: contract_id={contract_id}, len={len(new_summary)}"
            )
    except Exception:
        logger.exception(
            f"[ClauseSummary] contract summary merge failed: contract_id={contract_id}",
        )

    # 同步向量 chunks
    await _sync_contract_vectors(contract_id, completed_clauses)

    # 清理 pending_delete 条款
    if pending_delete_clauses:
        await ContractClause.filter(
            contract_id=contract_id, summary_status="pending_delete", is_deleted=False,
        ).update(is_deleted=True)
        logger.info(
            f"[ClauseSummary] cleaned {len(pending_delete_clauses)} pending_delete clauses: contract_id={contract_id}"
        )


async def _sync_contract_vectors(
    contract_id: int, completed_clauses: list[ContractClause],
) -> None:
    """同步合同概要 + 新完成条款的向量 chunks。"""
    from app.services.rag_service import rag_service
    from app.services.llm_builder import build_embed_model
    from app.models.rag import LLMProviderConfig, KnowledgeBase
    from llama_index.core.ingestion import IngestionPipeline
    from llama_index.core.schema import Document as LlamaDocument
    from llama_index.core.vector_stores import ExactMatchFilter, MetadataFilters

    contract = await Contract.filter(id=contract_id, is_deleted=False).first()
    if not contract:
        return

    doc = await Document.filter(id=contract.document_id).first()
    if not doc:
        return

    kb = await KnowledgeBase.filter(is_deleted=False).first()
    if not kb:
        return

    embedding_config = await LLMProviderConfig.get(id=kb.embedding_model_id)
    embed_model = build_embed_model(embedding_config)

    # 获取合同元信息
    party_a = ""
    party_b = ""
    contract_type = "其他"
    if contract.party_a_client_id:
        client = await Client.filter(id=contract.party_a_client_id).first()
        party_a = client.name if client else ""
    if contract.party_b_client_id:
        client = await Client.filter(id=contract.party_b_client_id).first()
        party_b = client.name if client else ""
    if contract.contract_type_id:
        ct = await ContractType.filter(id=contract.contract_type_id).first()
        contract_type = ct.name if ct else "其他"

    from app.schemas.vector_metadata import ContractMetadata

    if rag_service._vector_store:
        # 1. 删除合同概要的旧向量 chunks
        filters = MetadataFilters(
            filters=[
                ExactMatchFilter(key="source_doc_id", value=str(doc.id)),
                ExactMatchFilter(key="clause_index", value="0"),
            ],
            condition="and",
        )
        await rag_service._vector_store.adelete_nodes(filters=filters)

        # 2. 重新向量化合同概要 (clause_index=0)
        if contract.summary:
            header = (
                f"[合同概要: {doc.title} | "
                f"甲方: {party_a} | "
                f"乙方: {party_b} | "
                f"类型: {contract_type}]"
            )
            text = f"{header}\n{contract.summary}"
            summary_meta = ContractMetadata(
                title=doc.title,
                source_type=doc.source_type,
                knowledge_base_id=str(kb.id),
                source_doc_id=str(doc.id),
                doc_type_code=doc.doc_type_code,
                party_a=party_a,
                party_b=party_b,
                contract_type=contract_type,
                clause_index=0,
                clause_title="合同概要",
            )
            pipeline = IngestionPipeline(
                transformations=[embed_model],
                vector_store=rag_service._vector_store,
            )
            await pipeline.arun(documents=[
                LlamaDocument(text=text, metadata=summary_meta.to_dict()),
            ])
            logger.info(
                f"[ClauseSummary] contract summary vector synced: contract_id={contract_id}"
            )

        # 3. 同步新完成条款的向量 chunks
        for clause in completed_clauses:
            await _sync_single_clause_vector(
                clause, doc, kb, embed_model, party_a, party_b, contract_type,
            )


async def _sync_single_clause_vector(
    clause: ContractClause,
    doc: Document,
    kb,
    embed_model,
    party_a: str,
    party_b: str,
    contract_type: str,
) -> None:
    """同步单个条款的向量数据。"""
    from app.services.rag_service import rag_service
    from app.schemas.vector_metadata import ContractMetadata
    from llama_index.core.ingestion import IngestionPipeline
    from llama_index.core.schema import Document as LlamaDocument
    from llama_index.core.vector_stores import ExactMatchFilter, MetadataFilters

    content = clause.original_text or ""
    if not content.strip() or not rag_service._vector_store:
        return

    # 删除旧 chunks
    filters = MetadataFilters(
        filters=[
            ExactMatchFilter(key="source_doc_id", value=str(doc.id)),
            ExactMatchFilter(key="clause_index", value=str(clause.clause_index)),
        ],
        condition="and",
    )
    await rag_service._vector_store.adelete_nodes(filters=filters)

    # 切分 + 向量化
    sub_chunks = _split_clause_content(content, max_chars=500)
    llama_docs = []
    for sub_text in sub_chunks:
        header = (
            f"[合同: {doc.title} | "
            f"甲方: {party_a} | "
            f"乙方: {party_b} | "
            f"类型: {contract_type}] | "
            f"条款 {clause.clause_title}"
        )
        text = f"{header}\n{sub_text}"
        clause_meta = ContractMetadata(
            title=doc.title,
            source_type=doc.source_type,
            knowledge_base_id=str(kb.id),
            source_doc_id=str(doc.id),
            doc_type_code=doc.doc_type_code,
            party_a=party_a,
            party_b=party_b,
            contract_type=contract_type,
            clause_index=clause.clause_index,
            clause_title=clause.clause_title,
        )
        llama_docs.append(LlamaDocument(
            text=text, metadata=clause_meta.to_dict(),
        ))

    if llama_docs:
        pipeline = IngestionPipeline(
            transformations=[embed_model],
            vector_store=rag_service._vector_store,
        )
        await pipeline.arun(documents=llama_docs)
        logger.info(
            f"[ClauseSummary] clause vector synced: clause_id=%s, chunks=%s"
        )


def _split_clause_content(content: str, max_chars: int = 500) -> list[str]:
    """将条款内容按 max_chars 切分为子块。"""
    if len(content) <= max_chars:
        return [content]

    chunks = []
    for i in range(0, len(content), max_chars):
        chunk = content[i:i + max_chars].strip()
        if chunk:
            chunks.append(chunk)
    return chunks