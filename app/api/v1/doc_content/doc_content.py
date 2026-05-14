import logging

from fastapi import APIRouter, Query

from app.models.rag import Document
from app.schemas.base import Fail, Success
from app.schemas.chunks import ChunkCreate, ChunkUpdate
from app.services.chunk_service import chunk_service

logger = logging.getLogger(__name__)

router = APIRouter()


@router.get("/list", summary="文档切片列表")
async def list_doc_chunks(doc_id: int = Query(..., description="文档ID")):
    if not await Document.exists(id=doc_id, is_deleted=False):
        return Fail(msg="文档不存在")
    chunks = await chunk_service.list_by_doc_id(doc_id)
    return Success(data=chunks)


@router.post("/create", summary="新增切片")
async def create_chunk(body: ChunkCreate):
    if not await Document.exists(id=body.doc_id, is_deleted=False):
        return Fail(msg="文档不存在")
    try:
        node_id = await chunk_service.add_chunk(body.doc_id, body.text)
    except RuntimeError as e:
        return Fail(msg=str(e))
    except Exception as e:
        logger.error(f"[DocContent] Failed to add chunk: {e}")
        return Fail(msg=f"新增切片失败: {e}")
    return Success(msg="切片创建成功", data={"node_id": node_id})


@router.post("/update", summary="修改切片")
async def update_chunk(body: ChunkUpdate):
    if not await Document.exists(id=body.doc_id, is_deleted=False):
        return Fail(msg="文档不存在")
    try:
        new_node_id = await chunk_service.update_chunk(body.node_id, body.doc_id, body.text)
    except RuntimeError as e:
        return Fail(msg=str(e))
    except Exception as e:
        logger.error(f"[DocContent] Failed to update chunk: {e}")
        return Fail(msg=f"修改切片失败: {e}")
    return Success(msg="切片更新成功", data={"node_id": new_node_id})


@router.delete("/delete", summary="删除切片")
async def delete_chunk(node_id: str = Query(..., description="切片node_id")):
    try:
        await chunk_service.delete_chunk(node_id)
    except Exception as e:
        logger.error(f"[DocContent] Failed to delete chunk: {e}")
        return Fail(msg=f"删除切片失败: {e}")
    return Success(msg="删除成功")
