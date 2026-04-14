from fastapi import APIRouter

from .documents import router

documents_router = APIRouter()
documents_router.include_router(router, tags=["文档管理"])

__all__ = ["documents_router"]
