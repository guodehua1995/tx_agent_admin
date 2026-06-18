from fastapi import APIRouter

from app.core.dependency import DependPermission

from .agents import agents_router
from .ai_config import ai_config_router
from .apis import apis_router
from .auditlog import auditlog_router
from .base import base_router
from .dashboard import dashboard_router
from .depts import depts_router
from .doc_content import router as doc_content_router
from .doc_pages import router as doc_pages_router
from .doc_templates import doc_templates_router
from .documents import documents_router
from .feishu import feishu_router, webhook_router
from .feishu_folders import feishu_folders_router
from .global_config import global_config_router
from .kb_content import router as kb_content_router
from .knowledge_bases import knowledge_bases_router
from .menus import menus_router
from .quotation import quotation_router
from .reviews import reviews_router
from .roles import roles_router
from .users import users_router

v1_router = APIRouter()

v1_router.include_router(base_router, prefix="/base")
v1_router.include_router(users_router, prefix="/user", dependencies=[DependPermission])
v1_router.include_router(roles_router, prefix="/role", dependencies=[DependPermission])
v1_router.include_router(menus_router, prefix="/menu", dependencies=[DependPermission])
v1_router.include_router(apis_router, prefix="/api", dependencies=[DependPermission])
v1_router.include_router(depts_router, prefix="/dept", dependencies=[DependPermission])
v1_router.include_router(auditlog_router, prefix="/auditlog", dependencies=[DependPermission])

# RAG 模块路由
v1_router.include_router(documents_router, prefix="/document", dependencies=[DependPermission])
v1_router.include_router(reviews_router, prefix="/review", dependencies=[DependPermission])
v1_router.include_router(knowledge_bases_router, prefix="/knowledge_base", dependencies=[DependPermission])
v1_router.include_router(agents_router, prefix="/agent", dependencies=[DependPermission])
v1_router.include_router(ai_config_router, prefix="/ai_config", dependencies=[DependPermission])
v1_router.include_router(feishu_router, prefix="/feishu", dependencies=[DependPermission])
v1_router.include_router(feishu_folders_router, prefix="/feishu_folder", dependencies=[DependPermission])
v1_router.include_router(doc_templates_router, prefix="/doc_template", dependencies=[DependPermission])
v1_router.include_router(dashboard_router, prefix="/dashboard", dependencies=[DependPermission])
v1_router.include_router(global_config_router, prefix="/global_config", dependencies=[DependPermission])
v1_router.include_router(kb_content_router, prefix="/kb_content", dependencies=[DependPermission])
v1_router.include_router(doc_content_router, prefix="/doc_content", dependencies=[DependPermission])
v1_router.include_router(doc_pages_router, prefix="/doc_page", dependencies=[DependPermission])
v1_router.include_router(quotation_router, prefix="/quotation", dependencies=[DependPermission])

# 飞书 Webhook（无认证）
v1_router.include_router(webhook_router, prefix="/feishu")
