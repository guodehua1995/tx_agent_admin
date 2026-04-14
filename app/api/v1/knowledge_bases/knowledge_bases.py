import logging

from fastapi import APIRouter, Query
from tortoise.expressions import Q

from app.controllers.knowledge_base import knowledge_base_controller
from app.schemas.base import Success, SuccessExtra
from app.schemas.knowledge_bases import *

logger = logging.getLogger(__name__)

router = APIRouter()


@router.get("/list", summary="知识库列表")
async def list_knowledge_base(
    page: int = Query(1, description="页码"),
    page_size: int = Query(10, description="每页数量"),
    name: str = Query("", description="名称搜索"),
):
    q = Q(is_deleted=False)
    if name:
        q &= Q(name__contains=name)
    total, objs = await knowledge_base_controller.list(page=page, page_size=page_size, search=q, order=["-created_at"])
    data = [await obj.to_dict() for obj in objs]
    return SuccessExtra(data=data, total=total, page=page, page_size=page_size)


@router.get("/get", summary="知识库详情")
async def get_knowledge_base(kb_id: int = Query(..., description="知识库ID")):
    obj = await knowledge_base_controller.get(id=kb_id)
    return Success(data=await obj.to_dict())


@router.post("/create", summary="创建知识库")
async def create_knowledge_base(kb_in: KnowledgeBaseCreate):
    if not await LLMProviderConfig.exists(id=kb_in.embedding_model_id):
        return Fail(msg="Embedding模型配置不存在")
    await knowledge_base_controller.create(kb_in)
    logger.info("[KnowledgeBase] Created: name=%s", kb_in.name)
    return Success(msg="创建成功")


@router.post("/update", summary="更新知识库")
async def update_knowledge_base(kb_in: KnowledgeBaseUpdate):
    if kb_in.embedding_model_id is not None and not await LLMProviderConfig.exists(id=kb_in.embedding_model_id):
        return Fail(msg="Embedding模型配置不存在")
    await knowledge_base_controller.update(id=kb_in.id, obj_in=kb_in)
    logger.info("[KnowledgeBase] Updated: id=%s", kb_in.id)
    return Success(msg="更新成功")


@router.delete("/delete", summary="删除知识库")
async def delete_knowledge_base(kb_id: int = Query(..., description="知识库ID")):
    kb = await knowledge_base_controller.get(id=kb_id)
    kb.is_deleted = True
    await kb.save()
    await Document.filter(knowledge_base_id=kb_id, is_deleted=False).update(is_deleted=True)
    logger.info("[KnowledgeBase] Soft deleted: id=%s", kb_id)
    return Success(msg="删除成功")
    return Success(msg="删除成功")
