from fastapi import APIRouter

from .agents import router

agents_router = APIRouter()
agents_router.include_router(router, tags=["Agent管理"])

__all__ = ["agents_router"]
