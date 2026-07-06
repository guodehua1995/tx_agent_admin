"""
独立脚本: 添加 dev_bot_app_ids 全局配置项。
用法: python scripts/init_dev_bot_config.py

配置说明:
- dev_bot_app_ids: JSON 数组，存放开发环境专用 bot 的 app_id
- dev 环境: 仅启动列表中的 bot
- 其他环境: 排除列表中的 bot（避免测试 bot 干扰生产）
"""
import asyncio
import json
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from tortoise import Tortoise
from app.models.global_config import GlobalConfig
from app.settings.config import settings


async def main():
    await Tortoise.init(config=settings.TORTOISE_ORM)

    exists = await GlobalConfig.filter(config_key="dev_bot_app_ids").first()
    if exists:
        print(f"[SKIP] dev_bot_app_ids 已存在: {exists.config_value}")
        await Tortoise.close_connections()
        return

    await GlobalConfig.create(
        config_key="dev_bot_app_ids",
        config_value=json.dumps([], ensure_ascii=False),
        config_group="feishu",
        description="开发环境专用飞书 Bot app_id 列表（JSON 数组）。dev 环境仅启动列表中的 bot，其他环境排除列表中的 bot。",
    )
    print("[OK] 创建 dev_bot_app_ids 配置项（默认为空数组）")
    await Tortoise.close_connections()


if __name__ == "__main__":
    asyncio.run(main())