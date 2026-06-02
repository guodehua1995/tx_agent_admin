"""提取器基类与公共工具。"""

from pathlib import Path

import httpx

from app.controllers.feishu_bot import feishu_bot_controller
from app.log import logger
from app.models.enums import DocumentSourceType
from app.models.global_config import GlobalConfig
from app.models.rag import Document, DocumentPage
from app.services.feishu_service import feishu_service
from app.settings import settings


from . import ExtractionResult


# 文档转换器支持的文件扩展名
CONVERTIBLE_EXTENSIONS = {
    "docx", "doc", "pdf", "pptx", "ppt", "xlsx", "xls",
    "csv", "txt", "md", "png", "jpg", "jpeg",
}


class BaseExtractor:
    """提取器基类。子类按 doc_type_code 注册并实现 extract()。"""

    async def extract(self, doc: Document) -> ExtractionResult:
        raise NotImplementedError

    # ---------- 来源字节获取（按 source_type 复用） ----------

    async def _get_feishu_access_token(self) -> str:
        """获取飞书拉取机器人的 access_token 与 bot_config"""
        access_token = await feishu_service.get_tenant_access_token(
            settings.FEISHU_DOC_BOT_APPID, settings.FEISHU_DOC_BOT_APPSECRET
        )
        return access_token

    async def _fetch_file_bytes(self, doc: Document) -> tuple[bytes, str, str]:
        """统一从来源拿文件字节。

        - feishu_doc 来源：必须是 file 类型链接，下载文件
        - file_upload 来源：直接读 source_meta.file_path

        返回 (file_bytes, filename, ext_lower)
        """
        meta = doc.source_meta or {}

        if doc.source_type == DocumentSourceType.FEISHU_DOC:
            feishu_url = meta.get("feishu_url", "")
            doc_token, doc_type = feishu_service.parse_feishu_url(feishu_url)
            if doc_type == "slide":
                raise ValueError(
                    "飞书云文档PPT(slides类型)不支持通过API导出。"
                    "请使用飞书文件格式的链接(https://xxx.feishu.cn/file/xxx)"
                )
            if doc_type != "file":
                raise ValueError(
                    f"该文档类型需要文件来源，但飞书 URL 指向 {doc_type}。"
                    "请改用飞书 file 链接或 file_upload 来源。"
                )
            access_token = await self._get_feishu_access_token()
            file_bytes, filename = await feishu_service.download_file(doc_token, access_token)
            ext = Path(filename).suffix.lstrip(".").lower()
            logger.info(f"Feishu file downloaded: token={doc_token}, filename={filename}, size={len(file_bytes)}")
            return file_bytes, filename, ext

        if doc.source_type == DocumentSourceType.FILE_UPLOAD:
            file_path = meta.get("file_path", "")
            if not file_path:
                raise ValueError("文件路径为空")
            with open(file_path, "rb") as f:
                file_bytes = f.read()
            filename = Path(file_path).name
            ext = Path(file_path).suffix.lstrip(".").lower()
            return file_bytes, filename, ext

        raise ValueError(
            f"不支持的来源类型: {doc.source_type}（仅支持 feishu_doc / file_upload）"
        )

    async def _fetch_web_text(self, doc: Document) -> str:
        """从 WEB_URL 抓取 HTML/纯文本"""
        meta = doc.source_meta or {}
        url = meta.get("url", "")
        if not url:
            raise ValueError("URL 为空")
        async with httpx.AsyncClient() as client:
            resp = await client.get(url, follow_redirects=True)
            return resp.text

    # ---------- 分页落库（合同/PPT 共用） ----------

    @staticmethod
    def page_screenshot_key(doc_id: int, page_number: int) -> str:
        """页截图在存储后端的对象 key（统一路径规则）"""
        return f"pages/doc_{doc_id}/page_{page_number}.png"

    @staticmethod
    def doc_screenshot_prefix(doc_id: int) -> str:
        """文档级截图目录前缀，用于删除文档时批量清理"""
        return f"pages/doc_{doc_id}/"

    @staticmethod
    async def _save_page_records(doc: Document, pages: list) -> None:
        """保存页面截图并创建 DocumentPage 记录（仅当存在截图或多页时落库）

        DocumentPage.screenshot_url 字段语义为"对象 key"（如 pages/doc_3/page_1.png），
        前端展示前需经 file_storage.presign() 转换为可访问 URL。

        幂等保障：写入前先按 document_id 清理旧记录，避免文档重试时
        撞 (document_id, page_number) 唯一约束。
        """
        from app.services.file_storage import file_storage

        has_images = any(getattr(p, "image_bytes", None) for p in pages)
        if not has_images and len(pages) <= 1:
            return

        # 清理同文档旧的分页记录（重试场景必需）
        deleted = await DocumentPage.filter(document_id=doc.id).delete()
        if deleted:
            logger.info(f"Page records cleared before re-save: doc_id={doc.id}, deleted={deleted}")

        for page in pages:
            screenshot_key = None
            if page.image_bytes:
                key = BaseExtractor.page_screenshot_key(doc.id, page.page_number)
                screenshot_key = await file_storage.save(key, page.image_bytes)

            await DocumentPage.create(
                document_id=doc.id,
                page_number=page.page_number,
                total_pages=page.total_pages,
                content=page.content,
                screenshot_url=screenshot_key,
            )

        logger.info(f"Page records saved: doc_id={doc.id}, pages={len(pages)}")
