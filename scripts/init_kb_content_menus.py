"""
独立脚本: 向已有数据库中添加知识库内容管理的隐藏菜单项。
用法: python scripts/init_kb_content_menus.py
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

    # 查找 "知识管理" 目录菜单
    knowledge_menu = await Menu.filter(path="/rag-knowledge").first()
    if not knowledge_menu:
        print("[ERROR] 未找到 '知识管理' 目录菜单 (path=/rag-knowledge)，请先运行 init_rag_menus.py")
        await Tortoise.close_connections()
        return

    # 检查是否已添加过
    exists = await Menu.filter(path="kb-content", parent_id=knowledge_menu.id).exists()
    if exists:
        print("[SKIP] 知识库内容管理菜单已存在，跳过创建。")
        await Tortoise.close_connections()
        return

    print("[INFO] 开始创建知识库内容管理隐藏菜单...")

    new_menus = await Menu.bulk_create([
        Menu(
            menu_type=MenuType.MENU,
            name="知识库内容",
            path="kb-content",
            order=10,
            parent_id=knowledge_menu.id,
            icon="carbon:folder-open",
            is_hidden=True,
            component="/rag/kb-content",
            keepalive=False,
        ),
        Menu(
            menu_type=MenuType.MENU,
            name="文档分片",
            path="doc-content",
            order=11,
            parent_id=knowledge_menu.id,
            icon="carbon:text-align-left",
            is_hidden=True,
            component="/rag/doc-content",
            keepalive=False,
        ),
    ])

    # 获取新创建的菜单（bulk_create 可能不返回 id）
    created_menus = await Menu.filter(
        path__in=["kb-content", "doc-content"],
        parent_id=knowledge_menu.id,
    ).all()

    # 将新菜单分配给所有角色
    roles = await Role.all()
    for role in roles:
        await role.menus.add(*created_menus)
        print(f"  [OK] 已将新菜单分配给角色: {role.name}")

    print(f"\n[DONE] 已创建 2 个隐藏菜单项 (知识库内容、文档分片)，已分配给 {len(roles)} 个角色。")
    await Tortoise.close_connections()


if __name__ == "__main__":
    asyncio.run(main())
