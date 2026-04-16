"""
独立脚本: 向已有数据库中添加全局配置菜单。
用法: python scripts/init_global_config_menu.py
"""

import asyncio
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from tortoise import Tortoise

from app.models.admin import Menu, Role
from app.schemas.menus import MenuType
from app.settings.config import settings


async def main():
    await Tortoise.init(config=settings.TORTOISE_ORM)

    # 检查是否已存在
    exists = await Menu.filter(path="global-config").exists()
    if exists:
        print("[SKIP] 全局配置菜单已存在，跳过创建。")
        await Tortoise.close_connections()
        return

    # 找到父级目录：系统管理
    parent = await Menu.filter(path="/system").first()
    if not parent:
        print("[ERROR] 未找到系统管理目录 (path=/system)，请先执行 init_rag_menus.py")
        await Tortoise.close_connections()
        return

    menu = await Menu.create(
        menu_type=MenuType.MENU,
        name="全局配置",
        path="global-config",
        order=4,
        parent_id=parent.id,
        icon="carbon:settings",
        is_hidden=False,
        component="/rag/global-config",
        keepalive=False,
    )
    print(f"  [OK] 创建菜单: 全局配置 (id={menu.id})")

    # 分配给所有角色
    roles = await Role.all()
    for role in roles:
        await role.menus.add(menu)
        print(f"  [OK] 已分配给角色: {role.name}")

    print("\n[DONE] 全局配置菜单创建完成。")
    await Tortoise.close_connections()


if __name__ == "__main__":
    asyncio.run(main())
