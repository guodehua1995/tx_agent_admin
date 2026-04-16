from fastapi import APIRouter

from .global_config import router

global_config_router = APIRouter()
global_config_router.include_router(router, tags=["全局配置"])

__all__ = ["global_config_router"]
