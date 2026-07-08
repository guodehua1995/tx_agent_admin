"""合同管理 Service 层 — 业务逻辑编排"""

import json
import logging
from datetime import datetime
from typing import Optional

from app.controllers.contract import (
    contract_clause_controller,
    contract_controller,
    contract_type_controller,
)
from app.models.contract import Contract, ContractClause, ContractRiskReport, ContractType
from app.models.quotation import Client
from app.models.rag import Document

logger = logging.getLogger(__name__)


def _resolve_document_url(doc: Document | None) -> str | None:
    """从 Document 解析外部访问链接，兼容旧数据。"""
    if not doc or not doc.source_meta:
        return None
    meta = doc.source_meta
    source_type = doc.source_type
    if source_type == "feishu_doc":
        return meta.get("feishu_url") or None
    if source_type == "web_url":
        return meta.get("url") or None
    return None


class ContractService:
    """合同管理业务逻辑"""

    # ── 合同类型 ──────────────────────────────────────────────────

    async def list_contract_types(self) -> list[ContractType]:
        return await contract_type_controller.list_active()

    async def create_contract_type(self, name: str, code: str, description: str | None = None) -> ContractType:
        existing = await contract_type_controller.get_by_code(code)
        if existing:
            raise ValueError(f"合同类型编码 '{code}' 已存在")
        return await ContractType.create(name=name, code=code, description=description)

    async def match_or_create_contract_type(
        self, contract_name: str, snippet: str | None = None,
    ) -> ContractType:
        """LLM 匹配或创建合同类型（用于飞书文件夹监听自动入库）

        匹配策略：
        1. 精确匹配 — 文件名/片段中包含已知类型名
        2. 未匹配 — 归入"其他"，后续由管理员手动归类
        """
        active_types = await contract_type_controller.list_active()
        type_names = [t.name for t in active_types]

        search_text = f"{contract_name} {snippet or ''}"
        for t in active_types:
            if t.name in search_text or t.code in search_text.lower():
                return t

        # 未匹配，归入"其他"
        default = await contract_type_controller.get_by_code("other")
        if default:
            return default
        raise ValueError("未找到默认合同类型'其他'")

    # ── 合同 CRUD ─────────────────────────────────────────────────

    async def get_contract_detail(self, contract_id: int) -> dict:
        """获取合同详情（含甲方/乙方/类型名称）"""
        contract = await contract_controller.get(contract_id)
        if not contract or contract.is_deleted:
            raise ValueError(f"合同不存在: id={contract_id}")

        result = await contract.to_dict()

        # 关联查询
        if contract.contract_type_id:
            ct = await ContractType.filter(id=contract.contract_type_id).first()
            result["contract_type_name"] = ct.name if ct else None
        if contract.party_a_client_id:
            client = await Client.filter(id=contract.party_a_client_id).first()
            result["party_a_name"] = client.name if client else None
        if contract.party_b_client_id:
            client = await Client.filter(id=contract.party_b_client_id).first()
            result["party_b_name"] = client.name if client else None

        # 文档信息
        doc = await Document.filter(id=contract.document_id).first()
        if doc:
            result["document_title"] = doc.title
            result["document_status"] = doc.status
            result["document_url"] = contract.document_url or _resolve_document_url(doc)

        # 条款树
        clauses = await contract_clause_controller.get_tree_by_contract(contract_id)
        result["clauses"] = [
            await self._clause_to_dict(c) for c in clauses
        ]

        return result

    async def _clause_to_dict(self, clause: ContractClause) -> dict:
        d = await clause.to_dict()
        children = getattr(clause, "_children", [])
        if children:
            d["children"] = [await self._clause_to_dict(c) for c in children]
        return d

    async def update_contract(self, contract_id: int, **kwargs) -> Contract:
        contract = await contract_controller.get(contract_id)
        update_fields = {
            "contract_type_id", "party_a_client_id", "party_b_client_id",
            "project_name", "signing_date", "effective_date", "expiry_date",
            "total_amount", "summary",
        }
        for k, v in kwargs.items():
            if k in update_fields and v is not None:
                setattr(contract, k, v)
        await contract.save()
        return contract

    async def update_clause(self, clause_id: int, original_text: str) -> ContractClause:
        """更新条款原文（极速返回，后台异步摘要 + 向量同步）。"""
        clause = await ContractClause.filter(
            id=clause_id, is_deleted=False,
        ).exclude(summary_status="pending_delete").first()
        if not clause:
            raise ValueError(f"条款不存在: id={clause_id}")

        clause.original_text = original_text
        clause.summary_status = "pending_summary"
        await clause.save(update_fields=["original_text", "summary_status"])

        logger.info(
            "[Contract] clause updated: clause_id=%s, title=%s",
            clause_id, clause.clause_title,
        )
        return clause

    async def create_clause(
        self,
        contract_id: int,
        clause_title: str,
        original_text: str,
        parent_id: int | None = None,
    ) -> ContractClause:
        """新增条款（极速返回，后台异步摘要 + 向量同步）。

        clause_index 自动分配为当前合同最大序号 + 1。
        """
        contract = await Contract.filter(id=contract_id, is_deleted=False).first()
        if not contract:
            raise ValueError(f"合同不存在: id={contract_id}")

        # 计算 clause_index（排除 pending_delete 和概要 clause_index=0）
        max_clause = await ContractClause.filter(
            contract_id=contract_id, is_deleted=False,
        ).exclude(summary_status="pending_delete").order_by("-clause_index").first()
        new_index = (max_clause.clause_index + 1) if max_clause else 1

        # 计算 clause_level
        clause_level = 0
        if parent_id:
            parent = await ContractClause.filter(
                id=parent_id, contract_id=contract_id, is_deleted=False,
            ).exclude(summary_status="pending_delete").first()
            if not parent:
                raise ValueError(f"父条款不存在: id={parent_id}")
            clause_level = parent.clause_level + 1

        clause = await ContractClause.create(
            contract_id=contract_id,
            parent_id=parent_id,
            clause_index=new_index,
            clause_title=clause_title,
            clause_level=clause_level,
            original_text=original_text,
            sort_order=new_index,
            summary_status="pending_summary",
        )

        # 更新合同条款计数
        contract.clause_count = await ContractClause.filter(
            contract_id=contract_id, is_deleted=False,
        ).exclude(summary_status="pending_delete").count()
        await contract.save(update_fields=["clause_count"])

        logger.info(
            "[Contract] clause created: id=%s, title=%s, index=%s",
            clause.id, clause_title, new_index,
        )
        return clause

    async def delete_clause(self, clause_id: int):
        """删除条款（极速返回，标记 pending_delete 并立即清理向量）。

        同时标记所有子孙条款为 pending_delete，清理向量 chunks。
        """
        clause = await ContractClause.filter(
            id=clause_id, is_deleted=False,
        ).exclude(summary_status="pending_delete").first()
        if not clause:
            raise ValueError(f"条款不存在: id={clause_id}")

        # 收集所有需要删除的条款（自身 + 子孙）
        to_delete = await self._collect_descendant_ids(clause_id)
        to_delete.append(clause_id)

        # 立即删除向量 chunks
        clauses = await ContractClause.filter(id__in=to_delete).all()
        for c in clauses:
            await self._delete_clause_vector_chunks(c)

        # 标记为 pending_delete（不可见，等后台任务最终处理）
        await ContractClause.filter(id__in=to_delete).update(
            summary_status="pending_delete",
        )

        # 更新合同条款计数
        contract = await Contract.filter(id=clause.contract_id, is_deleted=False).first()
        if contract:
            contract.clause_count = await ContractClause.filter(
                contract_id=contract.id, is_deleted=False,
            ).exclude(summary_status="pending_delete").count()
            await contract.save(update_fields=["clause_count"])

        logger.info(
            "[Contract] clause deleted: id=%s, cascade=%s",
            clause_id, len(to_delete),
        )

    async def _collect_descendant_ids(self, parent_id: int) -> list[int]:
        """递归收集所有子孙条款 ID"""
        ids: list[int] = []
        children = await ContractClause.filter(
            parent_id=parent_id, is_deleted=False,
        ).exclude(summary_status="pending_delete").all()
        for child in children:
            ids.append(child.id)
            ids.extend(await self._collect_descendant_ids(child.id))
        return ids

    async def _delete_clause_vector_chunks(self, clause: ContractClause):
        """删除某条款在向量库中的所有 chunks"""
        from llama_index.core.vector_stores import ExactMatchFilter, MetadataFilters
        from app.services.rag_service import rag_service

        contract = await Contract.filter(id=clause.contract_id, is_deleted=False).first()
        if not contract or not rag_service._vector_store:
            return

        filters = MetadataFilters(
            filters=[
                ExactMatchFilter(key="source_doc_id", value=str(contract.document_id)),
                ExactMatchFilter(key="clause_index", value=str(clause.clause_index)),
            ],
            condition="and",
        )
        await rag_service._vector_store.adelete_nodes(filters=filters)
        logger.debug(
            "[Contract] deleted vector chunks: doc_id=%s, clause_index=%s",
            contract.document_id, clause.clause_index,
        )

    async def _sync_clause_vector(self, clause: ContractClause):
        """同步单条条款的向量数据：删旧 → 切分 → 向量化 → 入库"""
        from llama_index.core.ingestion import IngestionPipeline
        from llama_index.core.schema import Document as LlamaDocument
        from llama_index.core.vector_stores import ExactMatchFilter, MetadataFilters
        from app.services.document_pipeline import _split_clause_content
        from app.services.rag_service import rag_service
        from app.schemas.vector_metadata import ContractMetadata

        contract = await Contract.filter(id=clause.contract_id, is_deleted=False).first()
        if not contract:
            raise ValueError(f"合同不存在: id={clause.contract_id}")

        doc = await Document.filter(id=contract.document_id).first()
        if not doc:
            raise ValueError(f"文档不存在: id={contract.document_id}")

        # 查找知识库
        from app.models.rag import KnowledgeBase
        kb = await KnowledgeBase.filter(is_deleted=False).first()
        if not kb:
            raise ValueError("未找到可用的知识库")

        # 1. 删除该条款的旧向量 chunks（按 source_doc_id + clause_index）
        if rag_service._vector_store:
            filters = MetadataFilters(
                filters=[
                    ExactMatchFilter(key="source_doc_id", value=str(doc.id)),
                    ExactMatchFilter(key="clause_index", value=str(clause.clause_index)),
                ],
                condition="and",
            )
            await rag_service._vector_store.adelete_nodes(filters=filters)
            logger.debug(
                "[Contract] deleted old vector chunks: doc_id=%s, clause_index=%s",
                doc.id, clause.clause_index,
            )

        # 2. 重新切分 + 向量化
        content = clause.original_text or ""
        if not content.strip():
            return

        from app.services.llm_builder import build_embed_model
        from app.models.rag import LLMProviderConfig

        embedding_config = await LLMProviderConfig.get(id=kb.embedding_model_id)
        embed_model = build_embed_model(embedding_config)

        # 获取合同元信息（从已存在的 ContractClause 中推断）
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
                "[Contract] clause re-vectorized: clause_id=%s, chunks=%s",
                clause.id, len(llama_docs),
            )

    async def soft_delete_contract(self, contract_id: int):
        contract = await contract_controller.get(contract_id)
        contract.is_deleted = True
        await contract.save()

        # 同步软删条款
        await ContractClause.filter(
            contract_id=contract_id, is_deleted=False,
        ).exclude(summary_status="pending_delete").update(is_deleted=True)

        # 级联清理关联文档及其所有关联数据（向量、切片、页面、截图）
        if contract.document_id:
            from app.services.document_service import cleanup_document
            await cleanup_document(contract.document_id)
            logger.info(f"Contract delete: cascaded document cleanup contract_id={contract_id} document_id={contract.document_id}")

        # 清理审查报告
        deleted_reports = await ContractRiskReport.filter(contract_id=contract_id).delete()
        if deleted_reports:
            logger.info(f"Contract delete: risk reports deleted contract_id={contract_id} count={deleted_reports}")

        logger.info(f"Contract soft deleted: id={contract_id}")

    # ── 合同搜索 ──────────────────────────────────────────────────

    async def search_contracts(self, params: dict) -> dict:
        """结构化搜索合同"""
        total, items = await contract_controller.search(
            keyword=params.get("keyword"),
            party_a=params.get("party_a"),
            party_b=params.get("party_b"),
            contract_type_id=params.get("contract_type_id"),
            start_date=params.get("start_date"),
            end_date=params.get("end_date"),
            page=params.get("page", 1),
            page_size=params.get("page_size", 20),
        )

        result_items = []
        for item in items:
            d = await item.to_dict()
            if item.contract_type_id:
                ct = await ContractType.filter(id=item.contract_type_id).first()
                d["contract_type_name"] = ct.name if ct else None
            if item.party_a_client_id:
                client = await Client.filter(id=item.party_a_client_id).first()
                d["party_a_name"] = client.name if client else None
            if item.party_b_client_id:
                client = await Client.filter(id=item.party_b_client_id).first()
                d["party_b_name"] = client.name if client else None
            # 合同链接（优先取已落库字段，为空时动态解析 Document.source_meta）
            if not d.get("document_url"):
                doc = await Document.filter(id=item.document_id).first()
                d["document_url"] = _resolve_document_url(doc)
            result_items.append(d)

        # 批量查询审查状态
        if result_items:
            contract_ids = [it["id"] for it in result_items]
            reports = await ContractRiskReport.filter(
                contract_id__in=contract_ids,
            ).order_by("-created_at").all()
            status_map = {}
            for r in reports:
                if r.contract_id not in status_map:
                    status_map[r.contract_id] = r.status
            for it in result_items:
                it["review_status"] = status_map.get(it["id"])

        return {"total": total, "items": result_items}

    async def search_contract_summaries(self, params: dict) -> dict:
        """搜索合同摘要"""
        total, items = await contract_controller.search_by_summary(
            keyword=params.get("keyword"),
            party_a=params.get("party_a"),
            party_b=params.get("party_b"),
            page=params.get("page", 1),
            page_size=params.get("page_size", 20),
        )
        result_items = []
        for item in items:
            d = await item.to_dict()
            if not d.get("document_url"):
                doc = await Document.filter(id=item.document_id).first()
                d["document_url"] = _resolve_document_url(doc)
            result_items.append(d)
        return {"total": total, "items": result_items}

    async def search_clauses(self, params: dict) -> dict:
        """搜索条款"""
        total, items = await contract_clause_controller.search_clauses(
            keyword=params.get("keyword"),
            clause_title=params.get("clause_title"),
            contract_id=params.get("contract_id"),
            page=params.get("page", 1),
            page_size=params.get("page_size", 20),
        )
        return {"total": total, "items": [await item.to_dict() for item in items]}

    # ── 合同对比 ──────────────────────────────────────────────────

    async def compare_clause_summaries(
        self,
        clause_title: str,
        contract_ids: list[int] | None = None,
        party_a: str | None = None,
        party_b: str | None = None,
    ) -> list[dict]:
        """对比同类条款摘要"""
        total, items = await contract_clause_controller.find_similar_clauses(
            clause_title=clause_title,
            contract_ids=contract_ids,
            party_a=party_a,
            party_b=party_b,
            limit=20,
        )
        return [
            {
                "clause_id": item.id,
                "contract_id": item.contract_id,
                "clause_title": item.clause_title,
                "summary": item.summary,
                "clause_index": item.clause_index,
            }
            for item in items
        ]

    async def compare_clause_fulltext(
        self, clause_title: str, contract_ids: list[int],
    ) -> list[dict]:
        """对比同类条款全文"""
        total, items = await contract_clause_controller.find_similar_clauses(
            clause_title=clause_title,
            contract_ids=contract_ids,
            limit=50,
        )
        return [
            {
                "clause_id": item.id,
                "contract_id": item.contract_id,
                "clause_title": item.clause_title,
                "original_text": item.original_text,
                "clause_index": item.clause_index,
            }
            for item in items
        ]

    async def find_similar_contracts(self, contract_id: int, limit: int = 5) -> list[dict]:
        """查找相似合同（基于合同类型 + 同一甲方/乙方）"""
        source = await contract_controller.get(contract_id)
        if not source:
            return []

        q_parts = []
        if source.contract_type_id:
            q_parts.append(f"contract_type_id={source.contract_type_id}")
        if source.party_a_client_id:
            q_parts.append(f"party_a_client_id={source.party_a_client_id}")

        from tortoise.expressions import Q
        q = Q(is_deleted=False)
        if source.contract_type_id:
            q &= Q(contract_type_id=source.contract_type_id)
        if source.party_a_client_id:
            q |= Q(party_a_client_id=source.party_a_client_id)
        if source.party_b_client_id:
            q |= Q(party_b_client_id=source.party_b_client_id)

        from app.models.contract import Contract
        contracts = await Contract.filter(
            q, is_deleted=False,
        ).exclude(id=contract_id).limit(limit).all()

        result = []
        for c in contracts:
            d = await c.to_dict()
            if c.contract_type_id:
                ct = await ContractType.filter(id=c.contract_type_id).first()
                d["contract_type_name"] = ct.name if ct else None
            if not d.get("document_url"):
                doc = await Document.filter(id=c.document_id).first()
                d["document_url"] = _resolve_document_url(doc)
            result.append(d)

        return result

    # ── 合同统计 ──────────────────────────────────────────────────

    async def get_contract_stats(self) -> dict:
        """获取合同统计信息"""
        from tortoise.expressions import Count, Q

        total = await Contract.filter(is_deleted=False).count()

        # 按类型统计
        type_stats = await Contract.filter(is_deleted=False).annotate(
            count=Count("id"),
        ).group_by("contract_type_id").values("contract_type_id", "count")

        type_map = {}
        for ts in type_stats:
            ct_id = ts["contract_type_id"]
            if ct_id:
                ct = await ContractType.filter(id=ct_id).first()
                type_map[ct.name if ct else str(ct_id)] = ts["count"]

        # 按甲方统计
        party_a_stats = await Contract.filter(is_deleted=False).annotate(
            count=Count("id"),
        ).group_by("party_a_client_id").values("party_a_client_id", "count")

        party_map = {}
        for ps in party_a_stats:
            client_id = ps["party_a_client_id"]
            if client_id:
                client = await Client.filter(id=client_id).first()
                party_map[client.name if client else str(client_id)] = ps["count"]

        # 即将到期
        from datetime import datetime, timedelta
        now = datetime.now()
        deadline = now + timedelta(days=30)
        expiring = await Contract.filter(
            expiry_date__gte=now,
            expiry_date__lte=deadline,
            is_deleted=False,
        ).count()

        return {
            "total": total,
            "by_type": type_map,
            "by_party_a": party_map,
            "expiring_30_days": expiring,
        }

    async def get_contract_stats_sql(self) -> dict:
        """使用原生 SQL 获取合同统计（Agent 工具用）"""
        from tortoise import Tortoise
        conn = Tortoise.get_connection("postgres")

        result = {}

        # 总数
        rows = await conn.execute_query(
            "SELECT COUNT(*) as cnt FROM contract WHERE is_deleted = false"
        )
        result["total"] = rows[1][0]["cnt"] if rows[1] else 0

        # 按类型
        rows = await conn.execute_query("""
            SELECT ct.name, COUNT(c.id) as cnt
            FROM contract c
            LEFT JOIN contract_type ct ON c.contract_type_id = ct.id
            WHERE c.is_deleted = false
            GROUP BY ct.name
            ORDER BY cnt DESC
        """)
        result["by_type"] = {r["name"] or "未分类": r["cnt"] for r in rows[1]} if rows[1] else {}

        # 按甲方
        rows = await conn.execute_query("""
            SELECT cl.name, COUNT(c.id) as cnt
            FROM contract c
            JOIN quotation_client cl ON c.party_a_client_id = cl.id
            WHERE c.is_deleted = false
            GROUP BY cl.name
            ORDER BY cnt DESC
        """)
        result["by_party_a"] = {r["name"]: r["cnt"] for r in rows[1]} if rows[1] else {}

        # 即将到期
        rows = await conn.execute_query("""
            SELECT COUNT(*) as cnt
            FROM contract
            WHERE is_deleted = false
              AND expiry_date IS NOT NULL
              AND expiry_date >= NOW()
              AND expiry_date <= NOW() + INTERVAL '30 days'
        """)
        result["expiring_30_days"] = rows[1][0]["cnt"] if rows[1] else 0

        return result

    async def search_contracts_sql(self, keyword: str, limit: int = 10) -> list[dict]:
        """使用原生 SQL 搜索合同（Agent 工具用）"""
        from tortoise import Tortoise
        conn = Tortoise.get_connection("postgres")

        rows = await conn.execute_query("""
            SELECT c.id, c.project_name, c.summary, c.signing_date,
                   ct.name as contract_type_name,
                   cl_a.name as party_a_name, cl_b.name as party_b_name
            FROM contract c
            LEFT JOIN contract_type ct ON c.contract_type_id = ct.id
            LEFT JOIN quotation_client cl_a ON c.party_a_client_id = cl_a.id
            LEFT JOIN quotation_client cl_b ON c.party_b_client_id = cl_b.id
            WHERE c.is_deleted = false
              AND (c.project_name ILIKE $1 OR c.summary ILIKE $1)
            ORDER BY c.created_at DESC
            LIMIT $2
        """, [f"%{keyword}%", limit])

        return [dict(r) for r in rows[1]] if rows[1] else []

    # ── 合同审查 ──────────────────────────────────────────────────

    async def get_clause_tree(self, contract_id: int) -> list[dict]:
        """获取合同根级条款树（含子条款），供审查定时任务使用"""
        logger.debug(f"[get_clause_tree] contract_id={contract_id}")

        # 获取所有根级条款（clause_level=0）
        root_clauses = await ContractClause.filter(
            contract_id=contract_id,
            clause_level=0,
            is_deleted=False,
        ).order_by("clause_index")

        if not root_clauses:
            logger.debug(f"[get_clause_tree] No root clauses found for contract_id={contract_id}")
            return []

        tree = []
        for clause in root_clauses:
            # 获取子条款
            children = await ContractClause.filter(
                contract_id=contract_id,
                parent_id=clause.id,
                is_deleted=False,
            ).order_by("clause_index")

            tree.append({
                "clause_id": clause.id,
                "clause_index": clause.clause_index,
                "clause_title": clause.clause_title,
                "clause_level": clause.clause_level,
                "original_text": clause.original_text,
                "children": [
                    {
                        "clause_id": c.id,
                        "clause_index": c.clause_index,
                        "clause_title": c.clause_title,
                        "clause_level": c.clause_level,
                        "original_text": c.original_text,
                    }
                    for c in children
                ],
            })

        logger.debug(f"[get_clause_tree] Found {len(tree)} root clauses")
        return tree

    async def create_temporary_contract(
        self, content: str, file_name: str = "临时合同",
    ) -> Contract:
        """创建临时合同（不上传、不入库、不向量化，仅解析条款用于审查）

        流程：解析合同内容 → 创建 Contract(is_temporary=True) → 创建 ContractClause
        """
        logger.debug(f"[create_temporary_contract] file_name={file_name}")

        from app.services.temporary_contract import temporary_contract_processor

        # 解析合同
        parsed = await temporary_contract_processor.process(content, file_name)
        meta = parsed.get("meta", {})
        clauses = parsed.get("clauses", [])

        if not clauses:
            raise ValueError("合同解析失败：未提取到条款")

        logger.debug(
            f"[create_temporary_contract] Parsed {len(clauses)} clauses, "
            f"meta={meta}"
        )

        # 匹配/创建 ContractType
        contract_type_name = meta.get("contract_type", "其他")
        contract_type = await ContractType.filter(
            name=contract_type_name, is_deleted=False,
        ).first()
        if not contract_type:
            contract_type = await ContractType.filter(
                code="other", is_deleted=False,
            ).first()

        # 创建临时合同
        contract = await Contract.create(
            document_id=None,
            contract_type_id=contract_type.id if contract_type else None,
            party_a_client_id=0,
            party_b_client_id=None,
            project_name=file_name,
            clause_count=0,
            is_temporary=True,
        )

        # 创建条款树
        parent_map: dict[str, int] = {}
        clause_count = 0
        for clause in clauses:
            clause_index = clause.get("clause_index", 0)
            clause_title = clause.get("clause_title") or ""
            original_text = clause.get("content") or ""

            parts = [p.strip() for p in clause_title.split("-") if p.strip()]
            level = len(parts) - 1 if parts else 0

            parent_id = None
            if level > 0 and len(parts) > 1:
                parent_path = "-".join(parts[:-1])
                parent_id = parent_map.get(parent_path)

            await ContractClause.create(
                contract=contract,
                parent_id=parent_id,
                clause_index=clause_index,
                clause_title=clause_title if clause_title else None,
                clause_level=level,
                original_text=original_text,
                sort_order=clause_index,
            )

            full_path = "-".join(parts) if parts else str(clause_index)
            parent_map[full_path] = clause_count
            clause_count += 1

        contract.clause_count = clause_count
        await contract.save(update_fields=["clause_count"])

        logger.debug(
            f"[create_temporary_contract] Created: contract_id={contract.id}, "
            f"clauses={clause_count}"
        )
        return contract

    async def get_feishu_review_folder(self) -> str | None:
        """从 GlobalConfig 读取审查报告飞书文档存放目录"""
        from app.models.global_config import GlobalConfig

        config = await GlobalConfig.filter(
            config_key="contract_review_feishu_folder",
        ).first()

        if config:
            logger.debug(
                f"[get_feishu_review_folder] folder_token={config.config_value}"
            )
            return config.config_value

        logger.debug("[get_feishu_review_folder] No config found")
        return None


contract_service = ContractService()