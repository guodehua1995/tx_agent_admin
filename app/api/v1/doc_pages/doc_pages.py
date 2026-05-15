"""文档页面记录接口 — 查询 DocumentPage（PPT 页截图 + 内容）"""

import logging

from fastapi import APIRouter, Query

from app.models.rag import Document, DocumentPage
from app.schemas.base import Fail, Success

logger = logging.getLogger(__name__)

router = APIRouter()


@router.get("/list", summary="文档页面列表")
async def list_doc_pages(doc_id: int = Query(..., description="文档ID")):
    """按文档ID查询所有页面记录（含截图URL与内容）"""
    if not await Document.exists(id=doc_id, is_deleted=False):
        return Fail(msg="文档不存在")
    pages = await DocumentPage.filter(document_id=doc_id).order_by("page_number").values()
    return Success(data=pages)


@router.get("/detail", summary="文档页面详情")
async def get_doc_page(
    doc_id: int = Query(..., description="文档ID"),
    page_number: int = Query(..., description="页码"),
):
    """按文档ID和页码查询单个页面记录"""
    page = await DocumentPage.filter(
        document_id=doc_id, page_number=page_number,
    ).first()
    if not page:
        return Fail(msg="页面不存在")
    return Success(data={
        "id": page.id,
        "document_id": page.document_id,
        "page_number": page.page_number,
        "total_pages": page.total_pages,
        "content": page.content,
        "screenshot_url": page.screenshot_url,
    })
