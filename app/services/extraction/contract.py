"""合同文档提取器：将合同文件按页转换为 markdown，并落库 DocumentPage。"""

from app.models.rag import Document
from app.services.document_converter import document_converter

from . import ExtractionResult, register_extractor
from .base import CONVERTIBLE_EXTENSIONS, BaseExtractor


@register_extractor("contract")
class ContractExtractor(BaseExtractor):
    """合同提取：file 来源 → 文档转换器按页转 markdown，保留 pages 元数据"""

    async def extract(self, doc: Document) -> ExtractionResult:
        file_bytes, filename, ext = await self._fetch_file_bytes(doc)
        if ext not in CONVERTIBLE_EXTENSIONS:
            raise ValueError(f"合同不支持的文件类型: {filename} (扩展名: {ext})")

        pages = await document_converter.convert(file_bytes, ext, filename)
        await self._save_page_records(doc, pages)
        markdown_content = document_converter.pages_to_markdown(pages)

        return ExtractionResult(
            content=markdown_content,
            pages=list(pages),
            source_meta_patch={
                "filename": filename,
                "file_type": ext,
                "page_count": len(pages),
            },
        )
