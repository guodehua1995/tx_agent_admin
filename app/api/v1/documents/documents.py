from app.log import logger

from fastapi import APIRouter, BackgroundTasks, Query
from tortoise.expressions import Q

from app.controllers.document import document_controller
from app.core.ctx import CTX_USER_ID
from app.models.enums import DocumentTypeCode, DocumentStatus
from app.models.rag import Document, KnowledgeBase
from app.schemas.base import Fail, Success, SuccessExtra
from app.schemas.documents import (
    DocumentCreate,
    DocumentSubmitForReview,
    DocumentUpdate,
)
from app.services.document_pipeline import document_pipeline
from app.services.document_service import cleanup_document
from app.services.page_view import to_page_views

router = APIRouter()


# ========== 文档管理 ==========


@router.get("/list", summary="文档列表")
async def list_document(
    page: int = Query(1, description="页码"),
    page_size: int = Query(10, description="每页数量"),
    title: str = Query("", description="标题搜索"),
    status: str = Query("", description="状态过滤"),
    doc_type_code: str = Query("", description="文档类型编码"),
    knowledge_base_id: int = Query(None, description="知识库ID"),
    source_type: str = Query("", description="来源类型"),
):
   
    q = Q(is_deleted=False)
    if title:
        q &= Q(title__contains=title)
    if status:
        q &= Q(status=status)
    if doc_type_code:
        q &= Q(doc_type_code=doc_type_code)
    if knowledge_base_id is not None:
        q &= Q(knowledge_base_id=knowledge_base_id)
    if source_type:
        q &= Q(source_type=source_type)
    query = Document.filter(q).exclude(content="").order_by("-created_at")
    total = await query.count()
    objs = await query.offset((page - 1) * page_size).limit(page_size).only(
        "id", "title", "source_type", "source_meta", "doc_type_code",
        "status", "knowledge_base_id", "uploader_id", "error_message",
        "is_deleted", "created_at", "updated_at", "summary"
    )
    data = [await obj.to_dict(exclude_fields=["content"]) for obj in objs]
    return SuccessExtra(data=data, total=total, page=page, page_size=page_size)


@router.get("/get", summary="文档详情")
async def get_document(document_id: int = Query(..., description="文档ID")):
    obj = await document_controller.get(id=document_id)
    data = await obj.to_dict()
    # 附加分页摘要（分页文档使用）
    from app.models.rag import DocumentPage
    pages = await DocumentPage.filter(document_id=document_id).order_by("page_number").values(
        "id", "page_number", "total_pages", "screenshot_url"
    )
    data["pages"] = await to_page_views(pages)
    return Success(data=data)


@router.post("/create", summary="创建文档")
async def create_document(doc_in: DocumentCreate, background_tasks: BackgroundTasks):
    # 校验文档类型编码
    try:
        DocumentTypeCode(doc_in.doc_type_code)
    except ValueError:
        return Fail(msg=f"无效的文档类型编码: {doc_in.doc_type_code}")
    if not await KnowledgeBase.exists(id=doc_in.knowledge_base_id):
        return Fail(msg="知识库不存在")
    obj_dict = doc_in.model_dump()
    obj_dict["uploader_id"] = CTX_USER_ID.get()
    obj = await document_controller.create(obj_dict)
    background_tasks.add_task(document_pipeline.extract, obj.id)
    logger.info("[Document] Created: title=%s, id=%s", doc_in.title, obj.id)
    return Success(msg="文档创建成功，后台处理中", data={"id": obj.id})


@router.post("/update", summary="更新文档")
async def update_document(doc_in: DocumentUpdate):
    await document_controller.update(id=doc_in.id, obj_in=doc_in)
    logger.info("[Document] Updated: id=%s", doc_in.id)
    return Success(msg="更新成功")


@router.delete("/delete", summary="删除文档")
async def delete_document(document_id: int = Query(..., description="文档ID")):
    await document_controller.get(id=document_id)
    # 级联清理所有关联数据（向量、切片、页面）并软删除文档
    await cleanup_document(document_id)
    logger.info(f"Document deleted: id={document_id}")
    return Success(msg="删除成功")


@router.post("/retry", summary="重试处理文档")
async def retry_document(document_id: int = Query(..., description="文档ID"), background_tasks: BackgroundTasks = None):
    doc = await document_controller.get(id=document_id)
    if doc.status not in ("failed", "rejected"):
        return Fail(msg="只能重试失败或被驳回的文档")

    background_tasks.add_task(document_pipeline.retry, document_id)
    logger.info("[Document] Retry queued: id=%s", document_id)
    return Success(msg="已加入重试队列")


@router.post("/update_content", summary="编辑文档内容并重新提审")
async def update_document_content(body: DocumentSubmitForReview):
    await document_pipeline.resubmit(body.id, body.content)
    return Success(msg="内容已更新，已重新提交审核")


# ========== 文档类型（枚举接口，供前端下拉选择） ==========


@router.get("/type/list", summary="获取文档类型列表")
async def list_document_type():
    """返回所有可用的文档类型（纯枚举，无需分页）"""
    display_map = DocumentTypeCode.get_display_map()
    data = [
        {"code": code.value, "name": display_map.get(code, code.value)}
        for code in DocumentTypeCode
    ]
    return Success(data=data)
