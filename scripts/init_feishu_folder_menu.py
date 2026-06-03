"""
独立脚本: 向已有数据库中添加 飞书文件夹监听 菜单。
用法: python scripts/init_feishu_folder_menu.py
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

    # 检查是否已添加
    if await Menu.filter(path="feishu-folder").exists():
        print("[SKIP] 飞书文件夹菜单已存在，跳过创建。")
        await Tortoise.close_connections()
        return

    # 找到 飞书集成 目录
    feishu_menu = await Menu.filter(path="/rag-feishu").first()
    if not feishu_menu:
        print("[ERROR] 未找到 飞书集成 目录 (path=/rag-feishu)，请先执行 init_rag_menus.py")
        await Tortoise.close_connections()
        return

    print("[INFO] 开始创建 飞书文件夹监听 菜单...")
    folder_menu = await Menu.create(
        menu_type=MenuType.MENU,
        name="文件夹监听",
        path="feishu-folder",
        order=3,
        parent_id=feishu_menu.id,
        icon="carbon:folder-details",
        is_hidden=False,
        component="/rag/feishu-folder",
        keepalive=False,
    )
    print(f"  [OK] 飞书文件夹菜单已创建 (id={folder_menu.id})")

    # 将新菜单分配给所有角色
    roles = await Role.all()
    for role in roles:
        await role.menus.add(folder_menu)
        print(f"  [OK] 已将菜单分配给角色: {role.name}")

    print(f"\n[DONE] 飞书文件夹监听菜单创建完成，已分配给 {len(roles)} 个角色。")
    await Tortoise.close_connections()


if __name__ == "__main__":
    asyncio.run(main())
