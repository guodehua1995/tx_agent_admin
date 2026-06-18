"""
独立脚本: 向已有数据库中添加报价管理菜单。
用法: python scripts/init_quotation_menus.py
"""

import asyncio
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from tortoise import Tortoise

from app.models.admin import Menu, Role
from app.schemas.menus import MenuType
from app.settings.config import settings


MENUS_DEF = [
    # (name, path, order, icon, component)
    ("甲方管理", "quotation-client", 1, "carbon:enterprise", "/quotation/client"),
    ("报价规则", "quotation-rule", 2, "carbon:pricing-traditional", "/quotation/rule"),
    ("版本归档", "quotation-archive", 3, "carbon:archive", "/quotation/archive"),
]


async def main():
    await Tortoise.init(config=settings.TORTOISE_ORM)

    # 1. 创建一级目录「报价管理」
    parent = await Menu.filter(path="/quotation").first()
    if not parent:
        parent = await Menu.create(
            menu_type=MenuType.CATALOG,
            name="报价管理",
            path="/quotation",
            order=5,
            parent_id=0,
            icon="carbon:currency",
            is_hidden=False,
            component="",
            keepalive=False,
        )
        print(f"  [OK] 创建目录: 报价管理 (id={parent.id})")
    else:
        print("[SKIP] 报价管理目录已存在。")

    # 2. 创建子菜单
    created_menus = [parent]
    for name, path, order, icon, component in MENUS_DEF:
        exists = await Menu.filter(path=path).exists()
        if exists:
            print(f"  [SKIP] 菜单已存在: {name}")
            continue
        menu = await Menu.create(
            menu_type=MenuType.MENU,
            name=name,
            path=path,
            order=order,
            parent_id=parent.id,
            icon=icon,
            is_hidden=False,
            component=component,
            keepalive=False,
        )
        created_menus.append(menu)
        print(f"  [OK] 创建菜单: {name} (id={menu.id})")

    # 3. 分配给所有角色
    if len(created_menus) > 1:
        roles = await Role.all()
        for role in roles:
            for menu in created_menus:
                await role.menus.add(menu)
            print(f"  [OK] 已分配给角色: {role.name}")

    print("\n[DONE] 报价管理菜单创建完成。")
    await Tortoise.close_connections()


if __name__ == "__main__":
    asyncio.run(main())
