import logging

from fastapi import APIRouter, Query
from tortoise.expressions import Q

from app.controllers.ai_config import ai_config_controller
from app.schemas.ai_config import LLMProviderConfigCreate, LLMProviderConfigUpdate
from app.schemas.base import Fail, Success, SuccessExtra

logger = logging.getLogger(__name__)

router = APIRouter()


def mask_secret(value: str) -> str:
    """脱敏: 保留前3后3字符，中间用*代替"""
    if not value or len(value) <= 6:
        return "******"
    return value[:3] + "*" * (len(value) - 6) + value[-3:]


@router.get("/list", summary="AI模型配置列表")
async def list_ai_config(
    page: int = Query(1, description="页码"),
    page_size: int = Query(10, description="每页数量"),
    name: str = Query("", description="名称搜索"),
    is_embedding: bool = Query(None, description="是否Embedding模型"),
):
    q = Q()
    if name:
        q &= Q(name__contains=name)
    if is_embedding is not None:
        q &= Q(is_embedding=is_embedding)
    total, objs = await ai_config_controller.list(page=page, page_size=page_size, search=q, order=["-created_at"])
    data = []
    for obj in objs:
        d = await obj.to_dict()
        d["api_key"] = mask_secret(d.get("api_key", ""))
        data.append(d)
    return SuccessExtra(data=data, total=total, page=page, page_size=page_size)


@router.get("/get", summary="AI模型配置详情")
async def get_ai_config(config_id: int = Query(..., description="配置ID")):
    obj = await ai_config_controller.get(id=config_id)
    data = await obj.to_dict()
    data["api_key"] = mask_secret(data.get("api_key", ""))
    return Success(data=data)


@router.post("/create", summary="创建AI模型配置")
async def create_ai_config(config_in: LLMProviderConfigCreate):
    await ai_config_controller.create(config_in)
    logger.info("[AIConfig] Created: name=%s", config_in.name)
    return Success(msg="创建成功")


@router.post("/update", summary="更新AI模型配置")
async def update_ai_config(config_in: LLMProviderConfigUpdate):
    update_data = config_in.model_dump(exclude_unset=True, exclude={"id"})
    # 脱敏值含*号，说明用户未修改，不更新api_key
    if "api_key" in update_data and "*" in (update_data["api_key"] or ""):
        del update_data["api_key"]
    await ai_config_controller.update(id=config_in.id, obj_in=update_data)
    logger.info("[AIConfig] Updated: id=%s", config_in.id)
    return Success(msg="更新成功")


@router.delete("/delete", summary="删除AI模型配置")
async def delete_ai_config(config_id: int = Query(..., description="配置ID")):
    await ai_config_controller.remove(id=config_id)
    logger.info("[AIConfig] Deleted: id=%s", config_id)
    return Success(msg="删除成功")


@router.post("/test", summary="测试AI模型连接")
async def test_ai_config(config_id: int = Query(..., description="配置ID")):
    from app.services.rag_service import rag_service

    config = await ai_config_controller.get(id=config_id)
    ok = await rag_service.test_model_connection(config)
    if ok:
        return Success(msg="连接成功")
    return Fail(msg="连接失败")
