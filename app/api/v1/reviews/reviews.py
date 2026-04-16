import logging

from fastapi import APIRouter, BackgroundTasks, Query
from tortoise.expressions import Q

from app.controllers.document import document_controller
from app.controllers.review import review_controller
from app.core.ctx import CTX_USER_ID
from app.models.enums import DocumentStatus, ReviewAction
from app.models.rag import StructuredResult
from app.schemas.base import Fail, Success, SuccessExtra
from app.schemas.reviews import ReviewSubmit
from app.services.document_pipeline import document_pipeline

logger = logging.getLogger(__name__)

router = APIRouter()


@router.get("/list", summary="审核任务列表")
async def list_review(
    page: int = Query(1, description="页码"),
    page_size: int = Query(10, description="每页数量"),
    status: str = Query("", description="文档状态"),
):
    q = Q()
    if status:
        q &= Q(status=status)
    else:
        q &= Q(status=DocumentStatus.PENDING_REVIEW)
    total, objs = await document_controller.list(page=page, page_size=page_size, search=q, order=["-created_at"])
    data = [await obj.to_dict(exclude_fields=["content"]) for obj in objs]
    return SuccessExtra(data=data, total=total, page=page, page_size=page_size)


@router.get("/get", summary="审核详情")
async def get_review_detail(document_id: int = Query(..., description="文档ID")):
    doc = await document_controller.get(id=document_id)
    doc_dict = await doc.to_dict()

    structured = await StructuredResult.filter(document_id=document_id).first()
    doc_dict["structured_result"] = await structured.to_dict() if structured else None

    reviews = await review_controller.get_by_document(document_id)
    doc_dict["review_history"] = [await r.to_dict() for r in reviews]

    return Success(data=doc_dict)


@router.get("/history", summary="审核历史")
async def get_review_history(document_id: int = Query(..., description="文档ID")):
    reviews = await review_controller.get_by_document(document_id)
    data = [await r.to_dict() for r in reviews]
    return Success(data=data)


@router.post("/approve", summary="通过审核")
async def approve_document(
    review_in: ReviewSubmit,
    background_tasks: BackgroundTasks,
):
    doc = await document_controller.get(id=review_in.document_id)
    if doc.status != DocumentStatus.PENDING_REVIEW:
        return Fail(msg="该文档不在待审核状态")

    await review_controller.create(
        {
            "document_id": review_in.document_id,
            "reviewer_id": CTX_USER_ID.get(),
            "action": ReviewAction.APPROVE,
            "comment": review_in.comment,
            "edited_content": review_in.edited_content,
        }
    )

    doc.status = DocumentStatus.APPROVED
    await doc.save()

    background_tasks.add_task(document_pipeline.vectorize_document, doc.id)

    return Success(msg="审核通过")


@router.post("/reject", summary="驳回审核")
async def reject_document(review_in: ReviewSubmit):
    doc = await document_controller.get(id=review_in.document_id)
    if doc.status != DocumentStatus.PENDING_REVIEW:
        return Fail(msg="该文档不在待审核状态")

    await review_controller.create(
        {
            "document_id": review_in.document_id,
            "reviewer_id": CTX_USER_ID.get(),
            "action": ReviewAction.REJECT,
            "comment": review_in.comment,
        }
    )

    doc.status = DocumentStatus.REJECTED
    await doc.save()

    logger.info("[Review] Rejected: doc_id=%s, reviewer_id=%s", review_in.document_id, CTX_USER_ID.get())
    return Success(msg="已驳回")


@router.post("/publish_feishu", summary="发布结构化结果到飞书")
async def publish_to_feishu(
    structured_result_id: int = Query(..., description="结构化结果ID"),
    background_tasks: BackgroundTasks = None,
):
    background_tasks.add_task(document_pipeline.publish_to_feishu, structured_result_id)
    return Success(msg="已加入发布队列")
