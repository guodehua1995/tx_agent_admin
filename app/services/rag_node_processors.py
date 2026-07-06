"""RAG Node Postprocessors - 用于处理检索后的节点"""

from __future__ import annotations

import json
from typing import List, Optional

from llama_index.core.schema import NodeWithScore, QueryBundle

from app.log import logger


class TextOnlyPostProcessor:
    """
    清理节点，只保留文本内容，移除所有 metadata。
    
    用于减少传入 LLM 的上下文长度，避免 metadata 占用 token。
    """

    def postprocess_nodes(
        self,
        nodes: List[NodeWithScore],
        query_bundle: Optional[QueryBundle] = None,
    ) -> List[NodeWithScore]:
        """同步处理节点"""
        
        for node_with_score in nodes:
            # 只保留文本
            node_with_score.node.metadata = {}
        return nodes

    async def apostprocess_nodes(
        self,
        nodes: List[NodeWithScore],
        query_bundle: Optional[QueryBundle] = None,
    ) -> List[NodeWithScore]:
        """异步处理节点"""
        return self.postprocess_nodes(nodes, query_bundle)


class MetadataFilterPostProcessor:
    """
    保留指定的 metadata 字段，移除其他字段。
    
    Args:
        keep_keys: 要保留的 metadata key 列表
    """

    def __init__(self, keep_keys: Optional[List[str]] = None):
        self.keep_keys = set(keep_keys or [])

    def postprocess_nodes(
        self,
        nodes: List[NodeWithScore],
        query_bundle: Optional[QueryBundle] = None,
    ) -> List[NodeWithScore]:
        for node_with_score in nodes:
            if self.keep_keys:
                
                # 只保留指定的 keys
                node_with_score.node.metadata = {
                    k: v for k, v in node_with_score.node.metadata.items()
                    if k in self.keep_keys
                }
            else:
                # 清空所有 metadata
                node_with_score.node.metadata = {}
        return nodes

    async def apostprocess_nodes(
        self,
        nodes: List[NodeWithScore],
        query_bundle: Optional[QueryBundle] = None,
    ) -> List[NodeWithScore]:
        return self.postprocess_nodes(nodes, query_bundle)


class ContextExpansionPostProcessor:
    """上下文扩展后处理器 — PPT 邻页扩展 + 通用 chunk 窗口

    1. PPT 邻页: 当召回节点的 doc_type_code == "ppt" 时，
       从 DocumentPage 表查询 ±1 页的内容与截图，作为补充上下文返回。
    2. 通用 chunk 窗口: 当 context_chunks_window > 0 时，
       按同文档中 chunk 的自然顺序，向前后各扩展 N 个 chunk。
    """

    def __init__(self, context_chunks_window: int = 0):
        self.context_chunks_window = context_chunks_window

    def postprocess_nodes(
        self,
        nodes: List[NodeWithScore],
        query_bundle: Optional[QueryBundle] = None,
    ) -> List[NodeWithScore]:
        # 同步调用不做扩展（需要异步数据库查询）
        return nodes

    async def apostprocess_nodes(
        self,
        nodes: List[NodeWithScore],
        query_bundle: Optional[QueryBundle] = None,
    ) -> List[NodeWithScore]:
        if not nodes:
            return nodes

        expanded = list(nodes)

        # 收集已有 node_id 用于 chunk 去重
        seen_node_ids: set[str] = set()
        for n in nodes:
            nid = getattr(n.node, "node_id", None) or getattr(n.node, "id_", None)
            if nid:
                seen_node_ids.add(nid)

        # 收集已有 (doc_id, page_number) 用于 PPT 页去重
        seen_pages: set[tuple[str, int]] = set()
        for n in nodes:
            meta = n.node.metadata
            doc_id = meta.get("source_doc_id")
            pn = meta.get("page_number")
            if doc_id is not None and pn is not None:
                seen_pages.add((str(doc_id), int(pn)))

        # ── 1. PPT 邻页扩展 ──
        ppt_groups: dict[str, set[int]] = {}
        for n in nodes:
            meta = n.node.metadata
            if (
                meta.get("doc_type_code") == "ppt"
                and "source_doc_id" in meta
                and "page_number" in meta
            ):
                doc_id = str(meta["source_doc_id"])
                ppt_groups.setdefault(doc_id, set()).add(int(meta["page_number"]))

        if ppt_groups:
            new_nodes = await self._expand_ppt_pages(ppt_groups, seen_pages)
            expanded.extend(new_nodes)
            if new_nodes:
                logger.debug("[ContextExpansion] PPT adjacent pages added: %d", len(new_nodes))

        # ── 2. 通用 chunk 窗口扩展 ──
        if self.context_chunks_window > 0:
            new_nodes = await self._expand_chunk_window(nodes, seen_node_ids)
            expanded.extend(new_nodes)
            if new_nodes:
                logger.debug("[ContextExpansion] Chunk window expanded: %d", len(new_nodes))

        return expanded

    # ── PPT 邻页 ──

    async def _expand_ppt_pages(
        self,
        ppt_groups: dict[str, set[int]],
        seen_pages: set[tuple[str, int]],
    ) -> List[NodeWithScore]:
        from llama_index.core.schema import TextNode

        from app.models.rag import DocumentPage

        new_nodes: list[NodeWithScore] = []

        for doc_id, page_numbers in ppt_groups.items():
            # 计算需要的邻页号（±1）
            target_pages: set[int] = set()
            for pn in page_numbers:
                target_pages.update([pn - 1, pn + 1])
            # 排除已命中页 + 无效页码 + 已见过的页
            target_pages -= page_numbers
            target_pages = {
                p for p in target_pages
                if p >= 1 and (doc_id, p) not in seen_pages
            }
            if not target_pages:
                continue

            pages = await DocumentPage.filter(
                document_id=int(doc_id),
                page_number__in=list(target_pages),
            ).all()

            for dp in pages:
                node = TextNode(
                    text=dp.content or "",
                    metadata={
                        "source_doc_id": doc_id,
                        "page_id": dp.id,
                        "page_number": dp.page_number,
                        "doc_type_code": "ppt",
                        "screenshot_url": dp.screenshot_url,
                        "is_context_expansion": True,
                    },
                )
                new_nodes.append(NodeWithScore(node=node, score=0.0))
                seen_pages.add((doc_id, dp.page_number))

        return new_nodes

    # ── 通用 chunk 窗口 ──

    async def _expand_chunk_window(
        self,
        original_nodes: List[NodeWithScore],
        seen_node_ids: set[str],
    ) -> List[NodeWithScore]:
        import json as _json

        from llama_index.core.schema import TextNode

        from app.services.chunk_service import chunk_service

        new_nodes: list[NodeWithScore] = []

        for n in original_nodes:
            meta = n.node.metadata
            doc_id = meta.get("source_doc_id")
            node_id = getattr(n.node, "node_id", None) or getattr(n.node, "id_", None)
            if not doc_id or not node_id:
                continue

            adjacent = await chunk_service.get_adjacent_chunks(
                node_id=node_id,
                doc_id=str(doc_id),
                window=self.context_chunks_window,
            )

            for chunk in adjacent:
                cid = chunk["node_id"]
                if cid in seen_node_ids:
                    continue
                seen_node_ids.add(cid)

                chunk_meta = chunk.get("metadata_") or {}
                if isinstance(chunk_meta, str):
                    try:
                        chunk_meta = _json.loads(chunk_meta)
                    except (ValueError, TypeError):
                        chunk_meta = {}
                chunk_meta["is_context_expansion"] = True

                node = TextNode(text=chunk["text"], metadata=chunk_meta)
                new_nodes.append(NodeWithScore(node=node, score=0.0))

        return new_nodes


class ContractClauseSourcePostProcessor:
    """合同条款源文本后处理器。

    向量库中存储的是子 chunk，用于精准召回；本处理器将命中的子 chunk
    映射回 ContractClause 表中的完整条款原文，保证返回给 LLM 的上下文是完整条款。

    处理逻辑：
    1. 收集所有命中子 chunk 的 (source_doc_id, clause_index)
    2. 按 doc_id 查询 Contract → ContractClause，获取完整原文
    3. 用完整条款内容替换子 chunk 文本，并去重同条款
    4. 非合同文档保持原节点不变
    """

    async def apostprocess_nodes(
        self,
        nodes: List[NodeWithScore],
        query_bundle: Optional[QueryBundle] = None,
    ) -> List[NodeWithScore]:
        if not nodes:
            return nodes

        from llama_index.core.schema import NodeWithScore as _NodeWithScore, TextNode
        from app.models.contract import Contract, ContractClause
        from app.models.quotation import Client

        # 收集合同条款命中项
        hit_clauses: dict[str, set[int]] = {}
        for n in nodes:
            meta = n.node.metadata
            if meta.get("doc_type_code") == "contract" and "clause_index" in meta:
                doc_id = str(meta["source_doc_id"])
                clause_idx = int(meta["clause_index"])
                hit_clauses.setdefault(doc_id, set()).add(clause_idx)

        if not hit_clauses:
            return nodes

        # 从 Contract + ContractClause 表查询完整条款
        clause_cache: dict[tuple[int, int], dict] = {}
        contract_meta_cache: dict[int, dict] = {}

        for doc_id_str, clause_indices in hit_clauses.items():
            doc_id = int(doc_id_str)
            contract = await Contract.filter(document_id=doc_id, is_deleted=False).first()
            if not contract:
                continue

            # 缓存合同元信息
            if contract.id not in contract_meta_cache:
                meta_info = {"party_a": "", "party_b": "", "contract_type": ""}
                if contract.party_a_client_id:
                    client = await Client.filter(id=contract.party_a_client_id).first()
                    meta_info["party_a"] = client.name if client else ""
                if contract.party_b_client_id:
                    client = await Client.filter(id=contract.party_b_client_id).first()
                    meta_info["party_b"] = client.name if client else ""
                contract_meta_cache[contract.id] = meta_info

            # 查询条款
            clauses = await ContractClause.filter(
                contract_id=contract.id,
                clause_index__in=list(clause_indices),
                is_deleted=False,
            ).exclude(summary_status="pending_delete").all()

            for clause in clauses:
                clause_cache[(contract.id, clause.clause_index)] = {
                    "clause_title": clause.clause_title,
                    "original_text": clause.original_text,
                    "summary": clause.summary,
                }

        result: List[NodeWithScore] = []
        seen: set[tuple[int, int]] = set()

        for n in nodes:
            meta = n.node.metadata
            # 非合同节点直接保留
            if meta.get("doc_type_code") != "contract" or "clause_index" not in meta:
                result.append(n)
                continue

            doc_id = int(meta["source_doc_id"])
            clause_idx = int(meta["clause_index"])

            # 查找 contract
            contract = await Contract.filter(document_id=doc_id, is_deleted=False).first()
            if not contract:
                result.append(n)
                continue

            key = (contract.id, clause_idx)
            if key in seen:
                continue
            seen.add(key)

            clause_data = clause_cache.get(key)
            if not clause_data:
                # 找不到完整条款，退化为返回子 chunk 原文
                result.append(n)
                continue

            # 构建完整条款文本
            contract_meta = contract_meta_cache.get(contract.id, {})
            clause_title = clause_data["clause_title"] or str(clause_idx)
            header = (
                f"[合同: {meta.get('title', '')} | "
                f"甲方: {contract_meta.get('party_a', '')} | "
                f"乙方: {contract_meta.get('party_b', '')} | "
                f"类型: {contract_meta.get('contract_type', '')}] | "
                f"条款 {clause_title}"
            )
            full_text = f"{header}\n{clause_data['original_text']}"

            new_node = TextNode(
                text=full_text,
                metadata=meta,
            )
            result.append(_NodeWithScore(node=new_node, score=n.score))

        return result
