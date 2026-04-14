from fastapi import APIRouter

from .reviews import router

reviews_router = APIRouter()
reviews_router.include_router(router, tags=["审核管理"])

__all__ = ["reviews_router"]
