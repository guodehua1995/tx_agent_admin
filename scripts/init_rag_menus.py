"""
独立脚本: 向已有数据库中添加 RAG 模块菜单。
用法: python scripts/init_rag_menus.py
"""

import asyncio
import sys
import os

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from tortoise import Tortoise
from app.settings.config import settings
from app.models.admin import Menu, Role
from app.schemas.menus import MenuType


async def main():
    await Tortoise.init(config=settings.TORTOISE_ORM)

    # 检查是否已添加过 RAG 菜单（通过 path 判断）
    exists = await Menu.filter(path="/rag-knowledge").exists()
    if exists:
        print("[SKIP] RAG 菜单已存在，跳过创建。")
        await Tortoise.close_connections()
        return

    print("[INFO] 开始创建 RAG 菜单...")

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
    knowledge_children = await Menu.bulk_create([
        Menu(
            menu_type=MenuType.MENU, name="知识库管理", path="knowledge-base", order=1,
            parent_id=knowledge_menu.id, icon="carbon:data-base", is_hidden=False,
            component="/rag/knowledge-base", keepalive=False,
        ),
        Menu(
            menu_type=MenuType.MENU, name="文档管理", path="document", order=2,
            parent_id=knowledge_menu.id, icon="carbon:document-multiple", is_hidden=False,
            component="/rag/document", keepalive=False,
        ),
    ])
    print(f"  [OK] 知识管理: 1 个目录 + 2 个子菜单")

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
    print(f"  [OK] AI应用: 1 个目录 + 4 个子菜单")

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
    print(f"  [OK] 飞书集成: 1 个目录 + 2 个子菜单")

    # 将新菜单分配给所有角色
    new_menus = await Menu.filter(
        path__in=[
            "/rag-knowledge", "knowledge-base", "document",
            "/rag-ai", "ai-config", "agent", "review", "dashboard",
            "/rag-feishu", "feishu-bot", "conversation",
        ]
    ).all()

    roles = await Role.all()
    for role in roles:
        await role.menus.add(*new_menus)
        print(f"  [OK] 已将新菜单分配给角色: {role.name}")

    print(f"\n[DONE] 共创建 3 个目录 + 8 个子菜单，已分配给 {len(roles)} 个角色。")
    await Tortoise.close_connections()


if __name__ == "__main__":
    asyncio.run(main())
