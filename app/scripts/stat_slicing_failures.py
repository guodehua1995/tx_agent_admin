"""统计切片结果中包含"该条款解析失败"的文档数量及占比

用法：
    python -c "import asyncio; from app.scripts.stat_slicing_failures import run; print(asyncio.run(run()))"
"""

from tortoise import Tortoise, connections

from app.settings.config import settings


async def run() -> str:
    await Tortoise.init(config=settings.TORTOISE_ORM)

    try:
        conn = connections.get("postgres")
        
        # 放宽查询超时
        await conn.execute_query("SET LOCAL statement_timeout = 300000")
        
        # 总文档数（未删除）
        total_result = await conn.execute_query_dict(
            "SELECT COUNT(*) as cnt FROM document WHERE is_deleted = false"
        )
        total_docs = total_result[0]["cnt"] if total_result else 0
        
        # 有切片结果的文档数
        sliced_result = await conn.execute_query_dict(
            "SELECT COUNT(*) as cnt FROM slicing_result"
        )
        sliced_docs = sliced_result[0]["cnt"] if sliced_result else 0
        
        # 切片结果中包含失败标记的文档数
        failed_result = await conn.execute_query_dict(
            "SELECT COUNT(*) as cnt FROM slicing_result "
            "WHERE sliced_content LIKE '%该条款解析失败%' "
            "OR sliced_content LIKE '%该条款自动解析失败%'"
        )
        failed_docs = failed_result[0]["cnt"] if failed_result else 0
        
        # 切片结果中包含 ⚠️ 的文档数
        warning_result = await conn.execute_query_dict(
            "SELECT COUNT(*) as cnt FROM slicing_result "
            "WHERE sliced_content LIKE '%⚠️%'"
        )
        warning_docs = warning_result[0]["cnt"] if warning_result else 0

        lines = [
            "=" * 50,
            "合同条款切片失败统计",
            "=" * 50,
            f"总文档数（未删除）:          {total_docs}",
            f"已切片文档数:                {sliced_docs}",
            f"切片含'该条款解析失败':       {failed_docs}",
            f"切片含'⚠️'警告:              {warning_docs}",
            "-" * 50,
        ]

        if sliced_docs > 0:
            fail_rate = failed_docs / sliced_docs * 100
            warn_rate = warning_docs / sliced_docs * 100
            lines.append(f"失败占比（相对已切片）:     {fail_rate:.1f}% ({failed_docs}/{sliced_docs})")
            lines.append(f"警告占比（相对已切片）:     {warn_rate:.1f}% ({warning_docs}/{sliced_docs})")
        else:
            lines.append("无已切片文档")

        lines.append("=" * 50)
        return "\n".join(lines)

    finally:
        await Tortoise.close_connections()
