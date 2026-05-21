"""提取器基类与公共工具。"""

from pathlib import Path

import httpx

from app.controllers.feishu_bot import feishu_bot_controller
from app.log import logger
from app.models.enums import DocumentSourceType
from app.models.global_config import GlobalConfig
from app.models.rag import Document, DocumentPage
from app.services.feishu_service import feishu_service

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

    async def _get_feishu_access_token(self) -> tuple:
        """获取飞书拉取机器人的 access_token 与 bot_config"""
        global_config = await GlobalConfig.get(config_key="feishu_pull_bot")
        if not global_config:
            raise ValueError("没有配置飞书拉取机器人")
        bot_configs = await feishu_bot_controller.get_by_app_id(app_id=global_config.config_value)
        if not bot_configs:
            raise ValueError("没有可用的飞书机器人配置")
        access_token = await feishu_service.get_tenant_access_token(
            bot_configs.app_id, bot_configs.app_secret
        )
        return access_token, bot_configs

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
            access_token, _ = await self._get_feishu_access_token()
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
    async def _save_page_records(doc: Document, pages: list) -> None:
        """保存页面截图并创建 DocumentPage 记录（仅当存在截图或多页时落库）"""
        from app.services.file_storage import file_storage

        has_images = any(getattr(p, "image_bytes", None) for p in pages)
        if not has_images and len(pages) <= 1:
            return

        for page in pages:
            screenshot_url = None
            if page.image_bytes:
                path = f"pages/doc_{doc.id}/page_{page.page_number}.png"
                screenshot_url = await file_storage.save(path, page.image_bytes)

            await DocumentPage.create(
                document_id=doc.id,
                page_number=page.page_number,
                total_pages=page.total_pages,
                content=page.content,
                screenshot_url=screenshot_url,
            )

        logger.info(f"Page records saved: doc_id={doc.id}, pages={len(pages)}")
