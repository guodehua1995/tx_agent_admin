from fastapi import APIRouter

from .ai_config import router

ai_config_router = APIRouter()
ai_config_router.include_router(router, tags=["AI模型配置"])

__all__ = ["ai_config_router"]
