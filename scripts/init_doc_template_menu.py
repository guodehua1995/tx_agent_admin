"""
独立脚本: 向已有数据库中添加 文档模板 菜单。
用法: python scripts/init_doc_template_menu.py
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

    # 检查是否已添加过
    exists = await Menu.filter(path="doc-template").exists()
    if exists:
        print("[SKIP] 文档模板菜单已存在，跳过创建。")
        await Tortoise.close_connections()
        return

    # 找到 AI应用 目录
    ai_menu = await Menu.filter(path="/rag-ai").first()
    if not ai_menu:
        print("[ERROR] 未找到 AI应用 目录 (path=/rag-ai)，请先执行 init_rag_menus.py")
        await Tortoise.close_connections()
        return

    print("[INFO] 开始创建 文档模板 菜单...")

    doc_tpl_menu = await Menu.create(
        menu_type=MenuType.MENU,
        name="文档模板",
        path="doc-template",
        order=5,
        parent_id=ai_menu.id,
        icon="carbon:document-blank",
        is_hidden=False,
        component="/rag/doc-template",
        keepalive=False,
    )
    print(f"  [OK] 文档模板菜单已创建 (id={doc_tpl_menu.id})")

    # 将新菜单分配给所有角色
    roles = await Role.all()
    for role in roles:
        await role.menus.add(doc_tpl_menu)
        print(f"  [OK] 已将菜单分配给角色: {role.name}")

    print(f"\n[DONE] 文档模板菜单创建完成，已分配给 {len(roles)} 个角色。")
    await Tortoise.close_connections()


if __name__ == "__main__":
    asyncio.run(main())
