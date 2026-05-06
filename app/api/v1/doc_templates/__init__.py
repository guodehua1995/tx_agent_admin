from fastapi import APIRouter

from .doc_templates import router

doc_templates_router = APIRouter()
doc_templates_router.include_router(router, tags=["文档模板"])

__all__ = ["doc_templates_router"]
