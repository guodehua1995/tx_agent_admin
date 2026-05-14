import logging

from fastapi import APIRouter, BackgroundTasks, Query
from tortoise.expressions import Q

from app.controllers.document import document_controller
from app.core.ctx import CTX_USER_ID
from app.models.enums import DocumentTypeCode
from app.models.rag import KnowledgeBase
from app.schemas.base import Fail, Success, SuccessExtra
from app.schemas.documents import DocumentCreate
from app.services.chunk_service import chunk_service
from app.services.document_pipeline import document_pipeline

logger = logging.getLogger(__name__)

router = APIRouter()


@router.get("/list", summary="知识库文档列表")
async def list_kb_documents(
    kb_id: int = Query(..., description="知识库ID"),
    page: int = Query(1, description="页码"),
    page_size: int = Query(10, description="每页数量"),
    title: str = Query("", description="标题搜索"),
):
    if not await KnowledgeBase.exists(id=kb_id, is_deleted=False):
        return Fail(msg="知识库不存在")
    q = Q(knowledge_base_id=kb_id, is_deleted=False)
    if title:
        q &= Q(title__contains=title)
    total, objs = await document_controller.list(
        page=page, page_size=page_size, search=q, order=["-created_at"]
    )
    data = [await obj.to_dict(exclude_fields=["content"]) for obj in objs]
    return SuccessExtra(data=data, total=total, page=page, page_size=page_size)


@router.post("/create", summary="在知识库中创建文档")
async def create_kb_document(doc_in: DocumentCreate, background_tasks: BackgroundTasks):
    try:
        DocumentTypeCode(doc_in.doc_type_code)
    except ValueError:
        return Fail(msg=f"无效的文档类型编码: {doc_in.doc_type_code}")
    if not await KnowledgeBase.exists(id=doc_in.knowledge_base_id, is_deleted=False):
        return Fail(msg="知识库不存在")
    obj_dict = doc_in.model_dump()
    obj_dict["uploader_id"] = CTX_USER_ID.get()
    obj = await document_controller.create(obj_dict)
    background_tasks.add_task(document_pipeline.process_document, obj.id)
    logger.info("[KBContent] Document created: title=%s, kb_id=%s", doc_in.title, doc_in.knowledge_base_id)
    return Success(msg="文档创建成功，后台处理中", data={"id": obj.id})


@router.delete("/delete", summary="删除文档并清理向量")
async def delete_kb_document(document_id: int = Query(..., description="文档ID")):
    doc = await document_controller.get(id=document_id)
    # 清理向量
    await chunk_service.delete_by_doc_id(document_id)
    # 软删除文档
    doc.is_deleted = True
    await doc.save()
    logger.info("[KBContent] Document deleted with vectors: id=%s", document_id)
    return Success(msg="删除成功")
