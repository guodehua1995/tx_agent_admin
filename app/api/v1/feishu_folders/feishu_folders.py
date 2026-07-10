"""飞书文件夹监听 API"""

import logging

from fastapi import APIRouter, BackgroundTasks, Query
from tortoise.expressions import Q

from app.controllers.feishu_folder import feishu_folder_controller
from app.models.enums import DocumentTypeCode
from app.models.rag import Document, FeishuFolderFile, FeishuFolderWatch, KnowledgeBase
from app.schemas.base import Fail, Success, SuccessExtra
from app.schemas.feishu_folders import (
    FeishuFolderCreate,
    FeishuFolderToggle,
    FeishuFolderUpdate,
)
from app.services.feishu_folder_scan import feishu_folder_scan_service
from app.services.feishu_service import feishu_service

logger = logging.getLogger(__name__)

router = APIRouter()


def _validate_doc_type_code(code: str) -> bool:
    try:
        DocumentTypeCode(code)
        return True
    except ValueError:
        return False


@router.get("/list", summary="文件夹监听列表")
async def list_folder(
    page: int = Query(1, description="页码"),
    page_size: int = Query(10, description="每页数量"),
    name: str = Query("", description="名称搜索"),
    knowledge_base_id: int = Query(None, description="知识库ID"),
    is_active: bool = Query(None, description="启停状态"),
):
    q = Q(is_deleted=False)
    if name:
        q &= Q(name__contains=name)
    if knowledge_base_id is not None:
        q &= Q(knowledge_base_id=knowledge_base_id)
    if is_active is not None:
        q &= Q(is_active=is_active)
    total, objs = await feishu_folder_controller.list(
        page=page, page_size=page_size, search=q, order=["-created_at"]
    )
    data = [await obj.to_dict() for obj in objs]
    return SuccessExtra(data=data, total=total, page=page, page_size=page_size)


@router.get("/get", summary="文件夹监听详情")
async def get_folder(folder_id: int = Query(..., description="ID")):
    obj = await feishu_folder_controller.get(id=folder_id)
    if obj.is_deleted:
        return Fail(msg="监听已删除")
    data = await obj.to_dict()
    # 附加已扫描文件统计
    data["file_stats"] = {
        "total": await FeishuFolderFile.filter(folder_watch_id=folder_id).count(),
        "ingested": await FeishuFolderFile.filter(
            folder_watch_id=folder_id, ingest_status="ingested"
        ).count(),
        "failed": await FeishuFolderFile.filter(
            folder_watch_id=folder_id, ingest_status="failed"
        ).count(),
        "skipped": await FeishuFolderFile.filter(
            folder_watch_id=folder_id, ingest_status="skipped"
        ).count(),
    }
    return Success(data=data)


@router.post("/create", summary="新增文件夹监听")
async def create_folder(body: FeishuFolderCreate):
    if not _validate_doc_type_code(body.doc_type_code):
        return Fail(msg=f"无效的文档类型编码: {body.doc_type_code}")
    if not await KnowledgeBase.exists(id=body.knowledge_base_id):
        return Fail(msg="知识库不存在")

    try:
        folder_token = feishu_service.parse_feishu_folder_url(body.folder_url)
    except ValueError as e:
        return Fail(msg=str(e))

    if await FeishuFolderWatch.filter(folder_token=folder_token, is_deleted=False).exists():
        return Fail(msg="该文件夹已存在监听配置")

    obj = await FeishuFolderWatch.create(
        name=body.name,
        folder_token=folder_token,
        folder_url=body.folder_url,
        knowledge_base_id=body.knowledge_base_id,
        doc_type_code=body.doc_type_code,
        scan_interval_seconds=body.scan_interval_seconds or 600,
        auto_approve=body.auto_approve if body.auto_approve is not None else False,
        recursive_scan=body.recursive_scan if body.recursive_scan is not None else False,
        is_active=body.is_active if body.is_active is not None else True,
    )
    logger.info("[FeishuFolder] Created: name=%s, token=%s, id=%s", body.name, folder_token, obj.id)
    return Success(msg="创建成功", data={"id": obj.id})


@router.post("/update", summary="编辑文件夹监听")
async def update_folder(body: FeishuFolderUpdate):
    obj = await feishu_folder_controller.get(id=body.id)
    if obj.is_deleted:
        return Fail(msg="监听已删除")
    if body.doc_type_code and not _validate_doc_type_code(body.doc_type_code):
        return Fail(msg=f"无效的文档类型编码: {body.doc_type_code}")
    if body.knowledge_base_id is not None and not await KnowledgeBase.exists(id=body.knowledge_base_id):
        return Fail(msg="知识库不存在")
    # 不允许修改 folder_token；其它字段按 update_from_dict 写入
    update_data = body.model_dump(exclude_unset=True, exclude={"id"})
    if update_data:
        obj = obj.update_from_dict(update_data)
        await obj.save()
    logger.info("[FeishuFolder] Updated: id=%s", body.id)
    return Success(msg="更新成功")


@router.post("/toggle", summary="启停文件夹监听")
async def toggle_folder(body: FeishuFolderToggle):
    obj = await feishu_folder_controller.get(id=body.id)
    if obj.is_deleted:
        return Fail(msg="监听已删除")
    obj.is_active = body.is_active
    await obj.save()
    logger.info("[FeishuFolder] Toggled: id=%s, is_active=%s", body.id, body.is_active)
    return Success(msg="操作成功")


@router.delete("/delete", summary="删除文件夹监听")
async def delete_folder(folder_id: int = Query(..., description="ID")):
    await feishu_folder_controller.soft_delete(id=folder_id)
    logger.info("[FeishuFolder] Soft deleted: id=%s", folder_id)
    return Success(msg="删除成功")


@router.post("/scan_now", summary="立即扫描一次")
async def scan_folder_now(
    folder_id: int = Query(..., description="ID"),
    background_tasks: BackgroundTasks = None,
):
    obj = await feishu_folder_controller.get(id=folder_id)
    if obj.is_deleted:
        return Fail(msg="监听已删除")
    background_tasks.add_task(feishu_folder_scan_service.scan_one_now, folder_id)
    logger.info("[FeishuFolder] Manual scan queued: id=%s", folder_id)
    return Success(msg="已加入扫描队列")


@router.get("/files", summary="查看文件夹已扫描文件清单")
async def list_folder_files(
    folder_id: int = Query(..., description="文件夹监听ID"),
    page: int = Query(1, description="页码"),
    page_size: int = Query(20, description="每页数量"),
    ingest_status: str = Query("", description="入库状态过滤"),
):
    q = Q(folder_watch_id=folder_id)
    if ingest_status:
        q &= Q(ingest_status=ingest_status)
    total = await FeishuFolderFile.filter(q).count()
    objs = (
        await FeishuFolderFile.filter(q)
        .order_by("-created_at")
        .offset((page - 1) * page_size)
        .limit(page_size)
    )
    data = [await obj.to_dict() for obj in objs]

    # 批量查询关联 Document 的处理状态和标题（用于兜底 file_name）
    doc_ids = [obj.document_id for obj in objs if obj.document_id]
    if doc_ids:
        docs = await Document.filter(id__in=doc_ids).values("id", "status", "error_message", "title")
        doc_map = {d["id"]: d for d in docs}
        for item in data:
            did = item.get("document_id")
            if did and did in doc_map:
                item["doc_status"] = doc_map[did]["status"]
                item["doc_error_message"] = doc_map[did]["error_message"]
                # 兜底：如果 file_name 为空，使用 Document.title
                if not item.get("file_name"):
                    item["file_name"] = doc_map[did].get("title", "")
            else:
                item["doc_status"] = None
                item["doc_error_message"] = None
    else:
        for item in data:
            item["doc_status"] = None
            item["doc_error_message"] = None

    return SuccessExtra(data=data, total=total, page=page, page_size=page_size)


@router.post("/files/cleanup", summary="清理飞书侧已删除的文件")
async def cleanup_deleted_file(
    folder_id: int = Query(..., description="文件夹监听ID"),
    file_token: str = Query(..., description="飞书文件token"),
):
    """人工清理飞书侧已删除的文件：联动删除 Document + 向量 + 切片 + 页面。"""
    try:
        await feishu_folder_scan_service.cleanup_deleted_file(folder_id, file_token)
    except ValueError as e:
        return Fail(msg=str(e))
    return Success(msg="清理完成")


@router.post("/files/retry", summary="重试失败的文件夹监听文件")
async def retry_file(
    folder_id: int = Query(..., description="文件夹监听ID"),
    file_token: str = Query(..., description="飞书文件token"),
    background_tasks: BackgroundTasks = None,
):
    """手动重试：清理旧文档 → 重置为 pending → 下次扫描循环统一处理。"""
    try:
        new_doc_id = await feishu_folder_scan_service.retry_file(folder_id, file_token)
    except Exception as e:
        logger.exception(f"[FeishuFolder] retry failed: folder_id={folder_id}, token={file_token}")
        return Fail(msg=str(e))
    return Success(msg="已加入重试队列", data={"document_id": new_doc_id})
