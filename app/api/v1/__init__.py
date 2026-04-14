from fastapi import APIRouter

from app.core.dependency import DependPermission

from .agents import agents_router
from .ai_config import ai_config_router
from .apis import apis_router
from .auditlog import auditlog_router
from .base import base_router
from .dashboard import dashboard_router
from .depts import depts_router
from .documents import documents_router
from .feishu import feishu_router, webhook_router
from .knowledge_bases import knowledge_bases_router
from .menus import menus_router
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
v1_router.include_router(dashboard_router, prefix="/dashboard", dependencies=[DependPermission])

# 飞书 Webhook（无认证）
v1_router.include_router(webhook_router, prefix="/feishu")
