import logging

from fastapi import APIRouter, BackgroundTasks, Query
from tortoise.expressions import Q

from app.controllers.document import document_controller, document_type_controller
from app.core.ctx import CTX_USER_ID
from app.models.rag import DocumentType, KnowledgeBase
from app.schemas.base import Fail, Success, SuccessExtra
from app.models.enums import DocumentStatus
from app.schemas.documents import (
    DocumentCreate,
    DocumentSubmitForReview,
    DocumentTypeCreate,
    DocumentTypeUpdate,
    DocumentUpdate,
)
from app.services.document_pipeline import document_pipeline

logger = logging.getLogger(__name__)

router = APIRouter()


# ========== 文档管理 ==========


@router.get("/list", summary="文档列表")
async def list_document(
    page: int = Query(1, description="页码"),
    page_size: int = Query(10, description="每页数量"),
    title: str = Query("", description="标题搜索"),
    status: str = Query("", description="状态过滤"),
    doc_type_id: int = Query(None, description="文档类型ID"),
    knowledge_base_id: int = Query(None, description="知识库ID"),
    source_type: str = Query("", description="来源类型"),
):
    q = Q(is_deleted=False)
    if title:
        q &= Q(title__contains=title)
    if status:
        q &= Q(status=status)
    if doc_type_id is not None:
        q &= Q(doc_type_id=doc_type_id)
    if knowledge_base_id is not None:
        q &= Q(knowledge_base_id=knowledge_base_id)
    if source_type:
        q &= Q(source_type=source_type)
    total, objs = await document_controller.list(page=page, page_size=page_size, search=q, order=["-created_at"])
    data = [await obj.to_dict(exclude_fields=["content"]) for obj in objs]
    return SuccessExtra(data=data, total=total, page=page, page_size=page_size)


@router.get("/get", summary="文档详情")
async def get_document(document_id: int = Query(..., description="文档ID")):
    obj = await document_controller.get(id=document_id)
    return Success(data=await obj.to_dict())


@router.post("/create", summary="创建文档")
async def create_document(doc_in: DocumentCreate, background_tasks: BackgroundTasks):
    if not await DocumentType.exists(id=doc_in.doc_type_id):
        return Fail(msg="文档类型不存在")
    if not await KnowledgeBase.exists(id=doc_in.knowledge_base_id):
        return Fail(msg="知识库不存在")
    obj_dict = doc_in.model_dump()
    obj_dict["uploader_id"] = CTX_USER_ID.get()
    obj = await document_controller.create(obj_dict)
    background_tasks.add_task(document_pipeline.process_document, obj.id)
    logger.info("[Document] Created: title=%s, id=%s", doc_in.title, obj.id)
    return Success(msg="文档创建成功，后台处理中", data={"id": obj.id})


@router.post("/update", summary="更新文档")
async def update_document(doc_in: DocumentUpdate):
    await document_controller.update(id=doc_in.id, obj_in=doc_in)
    logger.info("[Document] Updated: id=%s", doc_in.id)
    return Success(msg="更新成功")


@router.delete("/delete", summary="删除文档")
async def delete_document(document_id: int = Query(..., description="文档ID")):
    doc = await document_controller.get(id=document_id)
    doc.is_deleted = True
    await doc.save()
    logger.info("[Document] Soft deleted: id=%s", document_id)
    return Success(msg="删除成功")


@router.post("/retry", summary="重试处理文档")
async def retry_document(document_id: int = Query(..., description="文档ID"), background_tasks: BackgroundTasks = None):
    doc = await document_controller.get(id=document_id)
    if doc.status not in ("failed", "rejected"):
        return Fail(msg="只能重试失败或被驳回的文档")
    background_tasks.add_task(document_pipeline.process_document, document_id)
    logger.info("[Document] Retry queued: id=%s", document_id)
    return Success(msg="已加入重试队列")


@router.post("/update_content", summary="编辑文档内容并重新提审")
async def update_document_content(body: DocumentSubmitForReview):
    doc = await document_controller.get(id=body.id)
    if doc.status != DocumentStatus.REJECTED:
        return Fail(msg="只有被驳回的文档才能编辑内容")
    doc.content = body.content
    doc.status = DocumentStatus.PENDING_REVIEW
    await doc.save()
    logger.info("[Document] Content updated and resubmitted: id=%s", body.id)
    return Success(msg="内容已更新，已重新提交审核")


# ========== 文档类型 ==========


@router.get("/type/list", summary="文档类型列表")
async def list_document_type(
    page: int = Query(1, description="页码"),
    page_size: int = Query(10, description="每页数量"),
):
    total, objs = await document_type_controller.list(page=page, page_size=page_size)
    data = [await obj.to_dict() for obj in objs]
    return SuccessExtra(data=data, total=total, page=page, page_size=page_size)


@router.post("/type/create", summary="创建文档类型")
async def create_document_type(type_in: DocumentTypeCreate):
    if await DocumentType.exists(code=type_in.code):
        return Fail(msg="文档类型编码已存在")
    if await DocumentType.exists(name=type_in.name):
        return Fail(msg="文档类型名称已存在")
    await document_type_controller.create(type_in)
    logger.info("[DocType] Created: code=%s", type_in.code)
    return Success(msg="创建成功")


@router.post("/type/update", summary="更新文档类型")
async def update_document_type(type_in: DocumentTypeUpdate):
    await document_type_controller.update(id=type_in.id, obj_in=type_in)
    logger.info("[DocType] Updated: id=%s", type_in.id)
    return Success(msg="更新成功")


@router.delete("/type/delete", summary="删除文档类型")
async def delete_document_type(type_id: int = Query(..., description="文档类型ID")):
    await document_type_controller.remove(id=type_id)
    logger.info("[DocType] Deleted: id=%s", type_id)
    return Success(msg="删除成功")
