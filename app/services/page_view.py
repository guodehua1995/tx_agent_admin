"""页面视图 helper — 把 DocumentPage 的对象 key 转成可访问 URL 后输出"""

from typing import Any, Iterable

from app.services.file_storage import file_storage


# 默认签名期限：Web 端审核/查看 = 1 天
DEFAULT_VIEW_EXPIRES = 24 * 3600
# 飞书机器人卡片侧使用的最大期限（火山 TOS 最大 7 天）
FEISHU_VIEW_EXPIRES = 7 * 24 * 3600


async def presign_screenshot(key: str | None, expires: int = DEFAULT_VIEW_EXPIRES) -> str | None:
    """把存储的对象 key 转换为可访问 URL；空 key 透传 None"""
    if not key:
        return None
    return await file_storage.presign(key, expires)


async def to_page_view(
    page: dict | Any,
    expires: int = DEFAULT_VIEW_EXPIRES,
) -> dict:
    """把 DocumentPage / dict 形态的数据规范为前端展示字典

    输出字段：id, page_number, total_pages, screenshot_url(签名后)
    其它已有键原样保留。
    """
    if isinstance(page, dict):
        data = dict(page)
    else:
        data = {
            "id": page.id,
            "document_id": page.document_id,
            "page_number": page.page_number,
            "total_pages": page.total_pages,
            "content": page.content,
            "screenshot_url": page.screenshot_url,
        }

    key = data.get("screenshot_url")
    data["screenshot_url"] = await presign_screenshot(key, expires)
    return data


async def to_page_views(
    pages: Iterable[dict | Any],
    expires: int = DEFAULT_VIEW_EXPIRES,
) -> list[dict]:
    return [await to_page_view(p, expires) for p in pages]
