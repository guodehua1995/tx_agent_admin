from aerich import Command
from fastapi import FastAPI
from fastapi.middleware import Middleware
from fastapi.middleware.cors import CORSMiddleware
from tortoise.expressions import Q

from app.api import api_router
from app.controllers.api import api_controller
from app.controllers.user import UserCreate, user_controller
from app.core.exceptions import (
    DoesNotExist,
    DoesNotExistHandle,
    HTTPException,
    HttpExcHandle,
    IntegrityError,
    IntegrityHandle,
    RequestValidationError,
    RequestValidationHandle,
    ResponseValidationError,
    ResponseValidationHandle,
)
from app.log import logger
from app.models.admin import Api, Menu, Role
from app.schemas.menus import MenuType
from app.settings.config import settings

from .middlewares import BackGroundTaskMiddleware, HttpAuditLogMiddleware


def make_middlewares():
    middleware = [
        Middleware(
            CORSMiddleware,
            allow_origins=settings.CORS_ORIGINS,
            allow_credentials=settings.CORS_ALLOW_CREDENTIALS,
            allow_methods=settings.CORS_ALLOW_METHODS,
            allow_headers=settings.CORS_ALLOW_HEADERS,
            expose_headers=settings.CORS_EXPOSE_HEADERS,
        ),
        Middleware(BackGroundTaskMiddleware),
        # Middleware(
        #     HttpAuditLogMiddleware,
        #     methods=["GET", "POST", "PUT", "DELETE"],
        #     exclude_paths=[
        #         "/api/v1/base/access_token",
        #         "/docs",
        #         "/openapi.json",
        #     ],
        # ),
    ]
    return middleware


def register_exceptions(app: FastAPI):
    app.add_exception_handler(DoesNotExist, DoesNotExistHandle)
    app.add_exception_handler(HTTPException, HttpExcHandle)
    app.add_exception_handler(IntegrityError, IntegrityHandle)
    app.add_exception_handler(RequestValidationError, RequestValidationHandle)
    app.add_exception_handler(ResponseValidationError, ResponseValidationHandle)


def register_routers(app: FastAPI, prefix: str = "/api"):
    app.include_router(api_router, prefix=prefix)


async def init_superuser():
    user = await user_controller.model.exists()
    if not user:
        await user_controller.create_user(
            UserCreate(
                username="admin",
                email="admin@admin.com",
                password="123456",
                is_active=True,
                is_superuser=True,
            )
        )


async def init_menus():
    menus = await Menu.exists()
    if not menus:
        parent_menu = await Menu.create(
            menu_type=MenuType.CATALOG,
            name="系统管理",
            path="/system",
            order=1,
            parent_id=0,
            icon="carbon:gui-management",
            is_hidden=False,
            component="Layout",
            keepalive=False,
            redirect="/system/user",
        )
        children_menu = [
            Menu(
                menu_type=MenuType.MENU,
                name="用户管理",
                path="user",
                order=1,
                parent_id=parent_menu.id,
                icon="material-symbols:person-outline-rounded",
                is_hidden=False,
                component="/system/user",
                keepalive=False,
            ),
            Menu(
                menu_type=MenuType.MENU,
                name="角色管理",
                path="role",
                order=2,
                parent_id=parent_menu.id,
                icon="carbon:user-role",
                is_hidden=False,
                component="/system/role",
                keepalive=False,
            ),
            Menu(
                menu_type=MenuType.MENU,
                name="菜单管理",
                path="menu",
                order=3,
                parent_id=parent_menu.id,
                icon="material-symbols:list-alt-outline",
                is_hidden=False,
                component="/system/menu",
                keepalive=False,
            ),
            Menu(
                menu_type=MenuType.MENU,
                name="API管理",
                path="api",
                order=4,
                parent_id=parent_menu.id,
                icon="ant-design:api-outlined",
                is_hidden=False,
                component="/system/api",
                keepalive=False,
            ),
            Menu(
                menu_type=MenuType.MENU,
                name="部门管理",
                path="dept",
                order=5,
                parent_id=parent_menu.id,
                icon="mingcute:department-line",
                is_hidden=False,
                component="/system/dept",
                keepalive=False,
            ),
            Menu(
                menu_type=MenuType.MENU,
                name="审计日志",
                path="auditlog",
                order=6,
                parent_id=parent_menu.id,
                icon="ph:clipboard-text-bold",
                is_hidden=False,
                component="/system/auditlog",
                keepalive=False,
            ),
        ]
        await Menu.bulk_create(children_menu)

        # --- 合同管理 ---
        contract_menu = await Menu.create(
            menu_type=MenuType.CATALOG,
            name="合同管理",
            path="/contract",
            order=2,
            parent_id=0,
            icon="carbon:document-signed",
            is_hidden=False,
            component="Layout",
            keepalive=False,
            redirect="/contract/list",
        )
        await Menu.bulk_create([
            Menu(
                menu_type=MenuType.MENU, name="合同列表", path="list", order=1,
                parent_id=contract_menu.id, icon="carbon:list", is_hidden=False,
                component="/contract/index", keepalive=False,
            ),
            Menu(
                menu_type=MenuType.MENU, name="合同类型", path="type", order=2,
                parent_id=contract_menu.id, icon="carbon:category", is_hidden=False,
                component="/contract/type", keepalive=False,
            ),
            # 隐藏子页面：合同详情
            Menu(
                menu_type=MenuType.MENU, name="合同详情", path="detail", order=10,
                parent_id=contract_menu.id, icon="carbon:document", is_hidden=True,
                component="/contract/detail", keepalive=False,
            ),
        ])

        # --- 知识管理 ---
        knowledge_menu = await Menu.create(
            menu_type=MenuType.CATALOG,
            name="知识管理",
            path="/rag-knowledge",
            order=3,
            parent_id=0,
            icon="carbon:document",
            is_hidden=False,
            component="Layout",
            keepalive=False,
            redirect="/rag-knowledge/knowledge-base",
        )
        await Menu.bulk_create([
            Menu(
                menu_type=MenuType.MENU, name="知识库管理", path="knowledge-base", order=1,
                parent_id=knowledge_menu.id, icon="carbon:data-base", is_hidden=False,
                component="/rag/knowledge-base", keepalive=False,
            ),
            Menu(
                menu_type=MenuType.MENU, name="文档类型", path="document-type", order=2,
                parent_id=knowledge_menu.id, icon="carbon:category", is_hidden=False,
                component="/rag/document-type", keepalive=False,
            ),
            Menu(
                menu_type=MenuType.MENU, name="文档管理", path="document", order=3,
                parent_id=knowledge_menu.id, icon="carbon:document-multiple", is_hidden=False,
                component="/rag/document", keepalive=False,
            ),
            Menu(
                menu_type=MenuType.MENU, name="全局配置", path="global-config", order=4,
                parent_id=knowledge_menu.id, icon="carbon:settings", is_hidden=False,
                component="/rag/global-config", keepalive=False,
            ),
            # 以下为隐藏子页面（不出现在侧边栏），需入库以生成前端动态路由与权限
            # 知识库详情下的“管理文档”页面
            Menu(
                menu_type=MenuType.MENU, name="知识库内容", path="kb-content", order=10,
                parent_id=knowledge_menu.id, icon="carbon:folder-open", is_hidden=True,
                component="/rag/kb-content", keepalive=False,
            ),
            # 文档详情下的“管理切片”页面
            Menu(
                menu_type=MenuType.MENU, name="文档分片", path="doc-content", order=11,
                parent_id=knowledge_menu.id, icon="carbon:text-align-left", is_hidden=True,
                component="/rag/doc-content", keepalive=False,
            ),
        ])

        # --- AI应用 ---
        ai_menu = await Menu.create(
            menu_type=MenuType.CATALOG,
            name="AI应用",
            path="/rag-ai",
            order=4,
            parent_id=0,
            icon="carbon:machine-learning-model",
            is_hidden=False,
            component="Layout",
            keepalive=False,
            redirect="/rag-ai/ai-config",
        )
        await Menu.bulk_create([
            Menu(
                menu_type=MenuType.MENU, name="模型配置", path="ai-config", order=1,
                parent_id=ai_menu.id, icon="carbon:settings-adjust", is_hidden=False,
                component="/rag/ai-config", keepalive=False,
            ),
            Menu(
                menu_type=MenuType.MENU, name="Agent管理", path="agent", order=2,
                parent_id=ai_menu.id, icon="carbon:bot", is_hidden=False,
                component="/rag/agent", keepalive=False,
            ),
            Menu(
                menu_type=MenuType.MENU, name="审核管理", path="review", order=3,
                parent_id=ai_menu.id, icon="carbon:checkmark-outline", is_hidden=False,
                component="/rag/review", keepalive=False,
            ),
            Menu(
                menu_type=MenuType.MENU, name="数据看板", path="dashboard", order=4,
                parent_id=ai_menu.id, icon="carbon:dashboard", is_hidden=False,
                component="/rag/dashboard", keepalive=False,
            ),
        ])

        # --- 飞书集成 ---
        feishu_menu = await Menu.create(
            menu_type=MenuType.CATALOG,
            name="飞书集成",
            path="/rag-feishu",
            order=5,
            parent_id=0,
            icon="carbon:chat-bot",
            is_hidden=False,
            component="Layout",
            keepalive=False,
            redirect="/rag-feishu/feishu-bot",
        )
        await Menu.bulk_create([
            Menu(
                menu_type=MenuType.MENU, name="机器人配置", path="feishu-bot", order=1,
                parent_id=feishu_menu.id, icon="carbon:connect", is_hidden=False,
                component="/rag/feishu-bot", keepalive=False,
            ),
            Menu(
                menu_type=MenuType.MENU, name="会话管理", path="conversation", order=2,
                parent_id=feishu_menu.id, icon="carbon:chat", is_hidden=False,
                component="/rag/conversation", keepalive=False,
            ),
        ])

        await Menu.create(
            menu_type=MenuType.MENU,
            name="一级菜单",
            path="/top-menu",
            order=10,
            parent_id=0,
            icon="material-symbols:featured-play-list-outline",
            is_hidden=False,
            component="/top-menu",
            keepalive=False,
            redirect="",
        )


async def init_apis():
    await api_controller.refresh_api()


async def init_db():
    command = Command(tortoise_config=settings.TORTOISE_ORM)
    try:
        await command.init_db(safe=True)
    except FileExistsError:
        pass

    await command.init()
    try:
        await command.upgrade(run_in_transaction=True)
        logger.info("[InitDB] Database migration completed")
    except Exception as e:
        logger.error(f"[InitDB] Migration failed: {e}. Please run 'aerich upgrade' manually.")
        raise


async def init_roles():
    roles = await Role.exists()
    if not roles:
        admin_role = await Role.create(
            name="管理员",
            desc="管理员角色",
        )
        user_role = await Role.create(
            name="普通用户",
            desc="普通用户角色",
        )

        # 分配所有API给管理员角色
        all_apis = await Api.all()
        await admin_role.apis.add(*all_apis)
        # 分配所有菜单给管理员和普通用户
        all_menus = await Menu.all()
        await admin_role.menus.add(*all_menus)
        await user_role.menus.add(*all_menus)

        # 为普通用户分配基本API
        basic_apis = await Api.filter(Q(method__in=["GET"]) | Q(tags="基础模块"))
        await user_role.apis.add(*basic_apis)


async def init_vector_store():
    """初始化 PGVector 向量存储

    注意：PGVectorStore(perform_setup=True) 会自动创建名为 data_<VECTOR_STORE_TABLE_NAME>
    的实际数据表（含 embedding 列、text_search_tsv 等），无需在此手动建表。
    """
    from tortoise import Tortoise
    from app.services.rag_service import rag_service

    try:
        await rag_service.init_vector_store()

        # 为 metadata 中的 knowledge_base_id 创建索引，加速按知识库过滤查询
        conn = Tortoise.get_connection("postgres")
        table = f"data_{settings.VECTOR_STORE_TABLE_NAME}"
        await conn.execute_query(
            f'CREATE INDEX IF NOT EXISTS idx_kb_id ON {table} ((metadata_->>\'knowledge_base_id\'));'
        )
    except Exception as e:
        logger.warning(f"Vector store initialization skipped: {e}")


async def init_feishu_ws_clients():
    """初始化飞书机器人长连接客户端"""
    import asyncio
    from app.services.feishu_ws_manager import feishu_ws_manager

    try:
        # 将当前事件循环传给管理器，用于同步回调中调度异步任务
        feishu_ws_manager.set_event_loop(asyncio.get_running_loop())
        await feishu_ws_manager.start_all()
    except Exception as e:
        logger.warning(f"Feishu WS clients initialization skipped: {e}")


async def init_redis():
    """初始化 Redis 连接"""
    from app.core.redis import init_redis as _init_redis

    try:
        await _init_redis()
    except Exception as e:
        logger.warning(f"Redis initialization skipped: {e}")


async def init_data():
    await init_db()
    logger.info("[InitData] Database initialized")
    await init_superuser()
    logger.info("[InitData] Superuser initialized")
    await init_menus()
    logger.info("[InitData] Menus initialized")
    await init_apis()
    logger.info("[InitData] APIs initialized")
    await init_roles()
    logger.info("[InitData] Roles initialized")
    await init_vector_store()
    logger.info("[InitData] Vector store initialized")
    await init_redis()
    logger.info("[InitData] Redis initialized")
    await init_feishu_ws_clients()
    logger.info("[InitData] Feishu WS clients initialized")
    # 确保 media 存储目录存在
    from pathlib import Path
    Path(settings.MEDIA_ROOT).mkdir(parents=True, exist_ok=True)
