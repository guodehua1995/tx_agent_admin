from fastapi import APIRouter

from .feishu import router, webhook_router

feishu_router = APIRouter()
feishu_router.include_router(router, tags=["飞书机器人"])

__all__ = ["feishu_router", "webhook_router"]
