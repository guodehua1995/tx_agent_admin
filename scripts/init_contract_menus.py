"""
独立脚本: 向已有数据库中添加合同管理模块菜单。
用法: python scripts/init_contract_menus.py
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

    # 检查是否已添加过合同管理菜单
    exists = await Menu.filter(path="/contract").exists()
    if exists:
        print("[SKIP] 合同管理菜单已存在，跳过创建。")
        await Tortoise.close_connections()
        return

    print("[INFO] 开始创建合同管理菜单...")

    # --- 合同管理 ---
    contract_menu = await Menu.create(
        menu_type=MenuType.CATALOG,
        name="合同管理",
        path="/contract",
        order=6,
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
            component="/contract", keepalive=False,
        ),
        Menu(
            menu_type=MenuType.MENU, name="合同对比", path="compare", order=2,
            parent_id=contract_menu.id, icon="carbon:compare", is_hidden=False,
            component="/contract/compare", keepalive=False,
        ),
        Menu(
            menu_type=MenuType.MENU, name="合同类型管理", path="type", order=3,
            parent_id=contract_menu.id, icon="carbon:category", is_hidden=False,
            component="/contract/type", keepalive=False,
        ),
        Menu(
            menu_type=MenuType.MENU, name="合同详情", path="detail", order=4,
            parent_id=contract_menu.id, icon="carbon:document-view", is_hidden=True,
            component="/contract/detail", keepalive=False,
        ),
    ])
    print(f"  [OK] 合同管理: 1 个目录 + 4 个子菜单(1个隐藏)")

    # 将新菜单分配给所有角色
    new_menus = await Menu.filter(
        path__in=[
            "/contract", "list", "compare", "type", "detail",
        ]
    ).all()

    roles = await Role.all()
    for role in roles:
        await role.menus.add(*new_menus)
        print(f"  [OK] 已将新菜单分配给角色: {role.name}")

    print(f"\n[DONE] 共创建 1 个目录 + 4 个子菜单，已分配给 {len(roles)} 个角色。")
    await Tortoise.close_connections()


if __name__ == "__main__":
    asyncio.run(main())