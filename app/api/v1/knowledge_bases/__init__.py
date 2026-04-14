from fastapi import APIRouter

from .knowledge_bases import router

knowledge_bases_router = APIRouter()
knowledge_bases_router.include_router(router, tags=["知识库管理"])

__all__ = ["knowledge_bases_router"]
