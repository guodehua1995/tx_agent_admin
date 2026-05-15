"""切片 CRUD 服务 — 封装对 knowledge_chunks 表的直接操作"""

from __future__ import annotations

import uuid

from tortoise import Tortoise

from app.log import logger
from app.models.rag import Document, KnowledgeBase, LLMProviderConfig
from app.services.llm_builder import build_embed_model
from app.settings import settings


class ChunkService:
    """管理 knowledge_chunks 表中的向量切片（无 ORM 模型，使用原生 SQL + LlamaIndex）"""

    @property
    def _table_name(self) -> str:
        # PGVectorStore 会自动在 table_name 前加 "data_" 前缀，实际数据表名为 data_<VECTOR_STORE_TABLE_NAME>
        return f"data_{settings.VECTOR_STORE_TABLE_NAME}"

    async def _get_connection(self):
        return Tortoise.get_connection("postgres")

    async def list_by_doc_id(self, doc_id: int) -> list[dict]:
        """列出某文档的所有切片"""
        conn = await self._get_connection()
        _, results = await conn.execute_query(
            f"SELECT id, node_id, text, metadata_ FROM {self._table_name} "
            f"WHERE metadata_->>'doc_id' = $1 ORDER BY id",
            [str(doc_id)],
        )
        return [dict(row) for row in results]

    async def add_chunk(self, doc_id: int, text: str) -> str:
        """新增切片: 构造 TextNode → 嵌入 → 写入 vector store"""
        from llama_index.core.schema import TextNode

        doc = await Document.get(id=doc_id)
        kb = await KnowledgeBase.get(id=doc.knowledge_base_id)
        embedding_config = await LLMProviderConfig.get(id=kb.embedding_model_id)
        embed_model = build_embed_model(embedding_config)

        node_id = str(uuid.uuid4())
        metadata = {
            "knowledge_base_id": str(kb.id),
            "doc_id": str(doc_id),
            "title": doc.title,
            "source_type": doc.source_type,
        }

        node = TextNode(
            id_=node_id,
            text=text,
            metadata=metadata,
        )

        # 嵌入文本
        embedding = await embed_model.aget_text_embedding(text)
        node.embedding = embedding

        # 写入 vector store
        from app.services.rag_service import rag_service

        if rag_service._vector_store is None:
            raise RuntimeError("Vector store 未初始化")
        await rag_service._vector_store.async_add([node])

        logger.info(f"Chunk added: node_id={node_id}, doc_id={doc_id}")
        return node_id

    async def update_chunk(self, node_id: str, doc_id: int, text: str) -> str:
        """修改切片: 删除旧节点 → 新增新节点（文本变化需重新嵌入）"""
        await self.delete_chunk(node_id)
        new_node_id = await self.add_chunk(doc_id, text)
        logger.info(f"Chunk updated: old={node_id} -> new={new_node_id}")
        return new_node_id

    async def delete_chunk(self, node_id: str):
        """按 node_id 删除单条切片"""
        conn = await self._get_connection()
        await conn.execute_query(
            f"DELETE FROM {self._table_name} WHERE node_id = $1",
            [node_id],
        )
        logger.info(f"Chunk deleted: node_id={node_id}")

    async def delete_by_doc_id(self, doc_id: int):
        """删除某文档的全部切片（供文档删除时调用）"""
        from app.services.rag_service import rag_service

        await rag_service.delete_document(str(doc_id))
        logger.info(f"All chunks deleted for doc_id={doc_id}")

    async def get_adjacent_chunks(
        self, node_id: str, doc_id: str, window: int = 1,
    ) -> list[dict]:
        """获取同文档中指定 chunk 前后 ±window 个相邻 chunk

        利用同文档 chunk 按 id 排序的行号(rn)定位目标 chunk，
        然后取 rn ± window 范围内的其他 chunk 返回。
        """
        if window <= 0:
            return []
        conn = await self._get_connection()
        sql = f"""
            WITH doc_chunks AS (
                SELECT node_id, text, metadata_,
                       ROW_NUMBER() OVER (ORDER BY id) AS rn
                FROM {self._table_name}
                WHERE metadata_->>'doc_id' = $1
            ),
            target AS (
                SELECT rn FROM doc_chunks WHERE node_id = $2
            )
            SELECT dc.node_id, dc.text, dc.metadata_
            FROM doc_chunks dc, target t
            WHERE dc.rn BETWEEN t.rn - $3 AND t.rn + $3
              AND dc.node_id != $2
            ORDER BY dc.rn
        """
        _, results = await conn.execute_query(sql, [doc_id, node_id, window])
        return [dict(row) for row in results]


chunk_service = ChunkService()
