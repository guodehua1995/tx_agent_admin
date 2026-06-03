from fastapi import APIRouter

from .feishu_folders import router

feishu_folders_router = APIRouter()
feishu_folders_router.include_router(router, tags=["飞书文件夹监听"])

__all__ = ["feishu_folders_router"]
