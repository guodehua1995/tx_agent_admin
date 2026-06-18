"""
一次性脚本: 修复 aerich 迁移记录，让 aerich 认为合并后的 init 已执行完毕。
用法: python scripts/fix_aerich_state.py

执行后数据库 aerich 表将只有一条 init 记录，与当前 migrations/models/ 目录一致。
"""

import asyncio
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from tortoise import Tortoise
from app.settings.config import settings


async def main():
    await Tortoise.init(config=settings.TORTOISE_ORM)
    conn = Tortoise.get_connection("postgres")

    # 清空 aerich 表并插入唯一的 init 版本记录
    await conn.execute_query("""
        DELETE FROM aerich;
    """)
    await conn.execute_query("""
        INSERT INTO aerich (version, app, content)
        VALUES ('0_20260525144238_init', 'models', '{}');
    """)

    print("[OK] aerich 表已重置，仅保留 init 迁移记录。")
    print("[INFO] 重新启动应用即可正常运行。")
    await Tortoise.close_connections()


if __name__ == "__main__":
    asyncio.run(main())
