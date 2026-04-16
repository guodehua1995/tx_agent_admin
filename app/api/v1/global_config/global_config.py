import logging

from fastapi import APIRouter, Query
from tortoise.exceptions import IntegrityError
from tortoise.expressions import Q

from app.controllers.global_config import global_config_controller
from app.schemas.base import Fail, Success, SuccessExtra
from app.schemas.global_config import (
    GlobalConfigBatchUpdate,
    GlobalConfigCreate,
    GlobalConfigUpdate,
)

logger = logging.getLogger(__name__)

router = APIRouter()


@router.get("/list", summary="全局配置列表")
async def list_global_config(
    page: int = Query(1, description="页码"),
    page_size: int = Query(10, description="每页数量"),
    config_group: str = Query("", description="配置分组"),
    config_key: str = Query("", description="配置键"),
):
    q = Q()
    if config_group:
        q &= Q(config_group=config_group)
    if config_key:
        q &= Q(config_key__contains=config_key)
    total, objs = await global_config_controller.list(
        page=page, page_size=page_size, search=q, order=["config_group", "config_key"]
    )
    data = [await obj.to_dict() for obj in objs]
    return SuccessExtra(data=data, total=total, page=page, page_size=page_size)


@router.get("/grouped", summary="按分组获取全局配置")
async def get_global_config_grouped():
    grouped = await global_config_controller.get_all_grouped()
    return Success(data=grouped)


@router.get("/get", summary="全局配置详情")
async def get_global_config(config_id: int = Query(..., description="配置ID")):
    obj = await global_config_controller.get(id=config_id)
    return Success(data=await obj.to_dict())


@router.post("/create", summary="创建全局配置")
async def create_global_config(config_in: GlobalConfigCreate):
    try:
        await global_config_controller.create(config_in)
    except IntegrityError:
        return Fail(msg="配置键已存在")
    logger.info("[GlobalConfig] Created: key=%s", config_in.config_key)
    return Success(msg="创建成功")


@router.post("/update", summary="更新全局配置")
async def update_global_config(config_in: GlobalConfigUpdate):
    update_data = config_in.model_dump(exclude_unset=True, exclude={"id"})
    try:
        await global_config_controller.update(id=config_in.id, obj_in=update_data)
    except IntegrityError:
        return Fail(msg="配置键已存在")
    logger.info("[GlobalConfig] Updated: id=%s", config_in.id)
    return Success(msg="更新成功")


@router.post("/batch_update", summary="批量更新全局配置")
async def batch_update_global_config(batch_in: GlobalConfigBatchUpdate):
    items = [item.model_dump() for item in batch_in.items]
    count = await global_config_controller.batch_update(items)
    logger.info("[GlobalConfig] Batch updated: %d items", count)
    return Success(msg=f"已更新 {count} 项配置")


@router.delete("/delete", summary="删除全局配置")
async def delete_global_config(config_id: int = Query(..., description="配置ID")):
    await global_config_controller.remove(id=config_id)
    logger.info("[GlobalConfig] Deleted: id=%s", config_id)
    return Success(msg="删除成功")
