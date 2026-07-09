"""
通用文档转换器

将多种格式的文件（docx, pdf, pptx, png, jpg, xlsx, csv, txt, md）统一转换为
标准化的 ConvertedPage 列表，为后续审核与切片入库提供统一输入。

架构：策略模式 + Handler 注册表，新增文件类型只需实现 BaseFileHandler 并注册。

文档转图片依赖 Gotenberg 服务（Docker 容器），通过 HTTP API 调用，
无需本地安装 LibreOffice。
"""

import csv
import os
from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from io import BytesIO
from pathlib import Path

import httpx

from app.log import logger
from app.settings import settings


# ============================================================
# 数据结构
# ============================================================


@dataclass
class ConvertedPage:
    """文档转换后的单页结构"""

    page_number: int  # 页码（从1开始）
    total_pages: int  # 总页数
    content: str  # Markdown 文本内容
    content_type: str  # "text_extracted" | "vision_extracted" | "table_extracted"
    source_file_type: str  # 原始文件扩展名: "docx"/"pdf"/"pptx" 等
    metadata: dict = field(default_factory=dict)  # 可扩展元数据
    image_bytes: bytes | None = None  # 原始页面 PNG 字节（仅 vision 类 handler 有值）


# ============================================================
# 异常定义
# ============================================================


class UnsupportedFileTypeError(Exception):
    """不支持的文件类型"""

    def __init__(self, file_type: str):
        super().__init__(f"不支持的文件类型: {file_type}")
        self.file_type = file_type


class ConversionError(Exception):
    """文档转换过程中的错误"""
    pass


# ============================================================
# Vision LLM 调用（供多个 Handler 共用）
# ============================================================


# 文档类 System Prompt（PDF、图片等以文本内容为主的场景）
DOCUMENT_VISION_PROMPT = """你是一个专业的文档内容解析专家。你的任务是分析文档页面的截图，将其内容转换为结构化的Markdown格式。

要求：
1. 准确识别页面中的所有文本内容（标题、正文、列表项等）
2. 保持原始的层级结构和逻辑关系
3. 识别并描述图表、图片等视觉元素的含义
4. 如果有表格，使用Markdown表格格式输出
5. 保留关键的数据和数字信息
6. 忽略纯装饰性元素（如背景图案、页码等）

# Markdown 标题层级映射规则（重要、必须严格遵守）
本任务是**逐页独立调用**，你看不到上一页与下一页。为了使跨页拼接后的 Markdown 层级一致，
**必须按原文中的「编号深度 / 语义层级」作为唯一依据判定标题级别**，不要根据字号大小、加粗、居中等**排版表象**反推层级。

合同 / 法律 / 报告类文档统一采用以下映射表：
| 语义层级 | Markdown | 示例原文形式 |
|---|---|---|
| 文档标题、封面、部编（Part） | `#`  | 《中华人民共和国服务合同》、Part I |
| 章 / Article / 一级数字编号 / 中文一、二、三、 | `##` | `1. DEFINITIONS`、`Article 1`、`一、总则` |
| 节 / 二级数字编号 / 该章下的子标题 | `###` | `1.1 服务范围`、`第一节`、`定义` |
| 条 / 三级数字编号 | `####` | `1.1.1 费用与支付` |
| 款 / 四级数字编号 | `#####` | `1.1.1.1` |

## 关键原则
1. **同一种编号形式必须映射到同一个 Markdown 层级**。如本页出现 `1. DEFINITIONS`、`2. SCOPE OF SERVICE`，尽管你只看到其中一个是本页首条、另一个是本页末条，也必须**都用 `##`**，不能一个 `##`、另一个 `###`。
2. **同一页中同级并列的标题必须用同样多的 `#`**。如本页同时出现 `1. DEFINITIONS`与`定義`（后者仅是前者的中文翻译副标题），应该识别为【同一个条款的双语表达】而不是【上下级】。双语合同推荐的输出形式：同一行合并为 `## 1. DEFINITIONS / 定义` 或仅保留其中一种语言作为 `##` 标题、另一语言紧跟作为正文；**不要拆成两级**（`##` + `###`）。
3. **不要根据页面上的字号/加粗/居中输出不同层级的标题**。例如一个合同中 `1. DEFINITIONS` 可能使用了加粗居中字体、`a. "Affiliate" means...` 使用了普通字体，仅凭字体差异你可能误判为 `## / ###`，但正确做法是：`1. DEFINITIONS` 识别为 `##`，下面的 `a. b. c.` **保留原样字母枚举，不提升为 Markdown 标题**。
4. **页首可能是上一页某条款的延续内容**（跨页）。若页首文本不是完整的编号起步（如仅是 `c. "..." means ...` 这样的枚举尾巴），不要凭空给它加上 `##` 标题，直接输出为正文。
5. **字母枚举 a. b. c.、罗马数字 (i)/(ii)、项目符•不使用 Markdown 标题**，保留原样。
6. 若页面是封面/目录/纯表格/附件清单，可以没有标题，直接输出表格或语义描述。

输出要求：
- 只输出该页内容的Markdown文本
- 不要添加额外解释或前缀
- 确保Markdown语法正确
- 不要输出"这一页包含..."之类的描述性文字，直接输出内容"""

# PPT 演示文稿 System Prompt（以视觉理解和内容提炼为主）
PPT_VISION_PROMPT = """你是一个专业的演示文稿内容分析专家。你的任务是理解PPT幻灯片页面截图的核心表达意图，提炼并总结其关键信息。

PPT页面通常包含标题、要点、图表、示意图、流程图等视觉元素，你需要：
1. 提取该页的主题/标题
2. 总结页面传达的核心观点和关键信息
3. 对图表、流程图、架构图等视觉元素进行含义解读，而非简单描述外观
4. 如果有数据图表，提取关键数据趋势和结论
5. 如果有表格，用Markdown表格格式输出关键数据
6. 忽略纯装饰性设计元素（背景、配色、Logo水印等）

输出要求：
- 以该页标题作为Markdown标题（## 级别）
- 用简洁的要点列表总结核心内容
- 对视觉元素给出含义解读而非外观描述
- 确保Markdown语法正确
- 不要输出"这一页包含..."之类的描述性前缀，直接输出结构化内容"""


# Vision LLM 调用默认参数
_VISION_LLM_TIMEOUT = 180  # 多模态单次调用超时（秒），图片理解较慢
_VISION_LLM_MAX_RETRIES = 2  # 额外重试次数


async def _call_vision_llm(
    image_bytes: bytes,
    page_num: int,
    context: str = "文档",
    system_prompt: str | None = None,
    timeout: int = _VISION_LLM_TIMEOUT,
    max_retries: int = _VISION_LLM_MAX_RETRIES,
) -> str:
    """调用多模态 LLM 理解图片内容（流式接收 + 超时控制 + 重试退避）

    Args:
        image_bytes: PNG 图片字节
        page_num: 页码
        context: 上下文描述（如"PPT"/"PDF"）
        system_prompt: 自定义系统提示词，默认使用 DOCUMENT_VISION_PROMPT
        timeout: 单次调用超时秒数
        max_retries: 额外重试次数

    Returns:
        LLM 返回的 Markdown 文本
    """
    import asyncio
    import base64

    from llama_index.core.llms import ChatMessage, ImageBlock, TextBlock
    from llama_index.llms.openai_like import OpenAILike

    from app.controllers.ai_config import ai_config_controller

    chat_models = await ai_config_controller.get_active_chat_models()
    if not chat_models:
        raise ConversionError("没有可用的 Chat 模型配置，无法处理图片内容")
    model_config = chat_models[0]

    extra = model_config.extra_config or {}
    llm = OpenAILike(
        api_base=model_config.api_base_url,
        api_key=model_config.api_key,
        model=model_config.model_name,
        max_tokens=model_config.max_tokens,
        temperature=extra.get("temperature", 0.3),
        is_chat_model=True,
    )

    image_b64 = base64.b64encode(image_bytes).decode("utf-8")
    image_url = f"data:image/png;base64,{image_b64}"

    prompt = system_prompt or DOCUMENT_VISION_PROMPT

    messages = [
        ChatMessage(role="system", content=prompt),
        ChatMessage(
            role="user",
            blocks=[
                TextBlock(text=f"请分析以下{context}第 {page_num} 页的内容，将其转换为Markdown格式："),
                ImageBlock(url=image_url),
            ],
        ),
    ]

    async def _stream_collect() -> str:
        response_gen = await llm.astream_chat(messages)
        chunks: list[str] = []
        final_message = ""
        async for resp in response_gen:
            delta = getattr(resp, "delta", None)
            if delta:
                chunks.append(delta)
            msg = getattr(resp, "message", None)
            if msg is not None and getattr(msg, "content", None):
                final_message = msg.content
        return ("".join(chunks) or final_message).strip()

    last_err: BaseException | None = None
    total_attempts = max_retries + 1
    for attempt in range(1, total_attempts + 1):
        try:
            result = await asyncio.wait_for(_stream_collect(), timeout=timeout)
            if not result:
                raise ConversionError("Vision LLM 返回空内容")
            return result
        except asyncio.TimeoutError as e:
            last_err = e
            err_repr = f"timeout({timeout}s)"
        except Exception as e:  # noqa: BLE001
            last_err = e
            err_repr = repr(e)

        if attempt < total_attempts:
            backoff = min(2 ** (attempt - 1), 10)
            logger.warning(
                f"[VisionLLM] page {page_num} call failed (attempt {attempt}/{total_attempts}, {err_repr}), retry in {backoff}ds"
            )
            await asyncio.sleep(backoff)
        else:
            logger.error(
                f"[VisionLLM] page {page_num} call exhausted retries ({total_attempts} attempts), last error: {err_repr}"
            )

    raise ConversionError(
        f"Vision LLM 调用失败 (page {page_num}, {total_attempts} attempts): {last_err}"
    )


# ============================================================
# Gotenberg 服务调用（替代本地 LibreOffice）
# ============================================================


def _get_gotenberg_url() -> str:
    """获取 Gotenberg 服务地址"""
    return getattr(settings, "GOTENBERG_URL", None) or os.getenv(
        "GOTENBERG_URL", "http://localhost:3000"
    )


async def _convert_to_pdf_via_gotenberg(file_bytes: bytes, filename: str) -> bytes:
    """通过 Gotenberg API 将 Office 文件转为 PDF

    Args:
        file_bytes: 文件二进制内容
        filename: 文件名（含扩展名，Gotenberg 据此判断格式）

    Returns:
        PDF 文件的字节内容
    """
    gotenberg_url = _get_gotenberg_url()
    url = f"{gotenberg_url}/forms/libreoffice/convert"

    logger.info(f"[Gotenberg] Converting {filename} to PDF via {gotenberg_url}")

    async with httpx.AsyncClient(timeout=180) as client:
        resp = await client.post(
            url,
            files={"files": (filename, file_bytes)},
        )
        if resp.status_code != 200:
            raise ConversionError(
                f"Gotenberg 转换失败: status={resp.status_code}, body={resp.text[:200]}"
            )
        return resp.content


async def _pdf_to_images_via_gotenberg(pdf_bytes: bytes) -> list[bytes]:
    """通过 Gotenberg API 将 PDF 转为每页 PNG 图片

    Gotenberg 的 /forms/chromium/convert/pdf 不直接支持 PDF→图片，
    所以这里使用 /forms/pdf/convert/merge 的替代方案：
    用 PyMuPDF (fitz) 在内存中将 PDF 渲染为图片，不需要 poppler。
    """
    import fitz  # PyMuPDF

    doc = fitz.open(stream=pdf_bytes, filetype="pdf")
    images = []
    for page in doc:
        # 渲染为 200 DPI 的 PNG
        mat = fitz.Matrix(200 / 72, 200 / 72)
        pix = page.get_pixmap(matrix=mat)
        images.append(pix.tobytes("png"))
    doc.close()

    logger.info(f"[DocumentConverter] PDF → {len(images)} page images (via PyMuPDF)")
    return images


# ============================================================
# Handler 基类
# ============================================================


class BaseFileHandler(ABC):
    """文件处理 Handler 基类"""

    @abstractmethod
    async def handle(self, file_stream: bytes, filename: str) -> list[ConvertedPage]:
        """处理文件流，返回 ConvertedPage 列表

        Args:
            file_stream: 文件二进制内容
            filename: 原始文件名（含扩展名）

        Returns:
            ConvertedPage 列表
        """
        ...


# ============================================================
# Handler 实现
# ============================================================


class DocxHandler(BaseFileHandler):
    """DOCX 文件处理：mammoth 提取纯文字转 Markdown"""

    async def handle(self, file_stream: bytes, filename: str) -> list[ConvertedPage]:
        import mammoth

        result = mammoth.convert_to_markdown(BytesIO(file_stream))
        content = result.value

        if result.messages:
            for msg in result.messages:
                logger.debug(f"[DocxHandler] mammoth message: {msg}")

        if not content.strip():
            content = "(文档内容为空)"

        return [
            ConvertedPage(
                page_number=1,
                total_pages=1,
                content=content,
                content_type="text_extracted",
                source_file_type="docx",
                metadata={"filename": filename},
            )
        ]


class PdfHandler(BaseFileHandler):
    """PDF 文件处理：每页转图片 → Vision LLM → Markdown"""

    async def handle(self, file_stream: bytes, filename: str) -> list[ConvertedPage]:
        # PDF → 每页 PNG（通过 PyMuPDF 在内存中渲染）
        page_images = await _pdf_to_images_via_gotenberg(file_stream)

        if not page_images:
            raise ConversionError("PDF 文件没有任何页面内容")

        total = len(page_images)
        pages = []
        for i, img_bytes in enumerate(page_images, start=1):
            logger.info(f"[PdfHandler] Processing page {i}/{total}")
            try:
                page_md = await _call_vision_llm(img_bytes, i, context="PDF文档")
                pages.append(
                    ConvertedPage(
                        page_number=i,
                        total_pages=total,
                        content=page_md,
                        content_type="vision_extracted",
                        source_file_type="pdf",
                        metadata={"filename": filename},
                        image_bytes=img_bytes,
                    )
                )
            except Exception as e:
                logger.error(f"[PdfHandler] Page {i} failed: {e}")
                pages.append(
                    ConvertedPage(
                        page_number=i,
                        total_pages=total,
                        content=f"> [页面处理失败: {str(e)}]",
                        content_type="vision_extracted",
                        source_file_type="pdf",
                        metadata={"filename": filename, "error": str(e)},
                        image_bytes=img_bytes,
                    )
                )
        return pages


class PptxHandler(BaseFileHandler):
    """PPTX 文件处理：Gotenberg → PDF → 每页图片 → Vision LLM → Markdown"""

    async def handle(self, file_stream: bytes, filename: str) -> list[ConvertedPage]:
        # PPT → PDF（通过 Gotenberg）
        pdf_bytes = await _convert_to_pdf_via_gotenberg(file_stream, filename or "input.pptx")

        # PDF → 每页 PNG（通过 PyMuPDF）
        page_images = await _pdf_to_images_via_gotenberg(pdf_bytes)

        if not page_images:
            raise ConversionError("PPT 文件没有任何页面内容")

        total = len(page_images)
        pages = []
        for i, img_bytes in enumerate(page_images, start=1):
            logger.info(f"[PptxHandler] Processing page {i}/{total}")
            try:
                page_md = await _call_vision_llm(
                    img_bytes, i, context="PPT", system_prompt=PPT_VISION_PROMPT
                )
                pages.append(
                    ConvertedPage(
                        page_number=i,
                        total_pages=total,
                        content=page_md,
                        content_type="vision_extracted",
                        source_file_type="pptx",
                        metadata={"filename": filename},
                        image_bytes=img_bytes,
                    )
                )
            except Exception as e:
                logger.error(f"[PptxHandler] Page {i} failed: {e}")
                pages.append(
                    ConvertedPage(
                        page_number=i,
                        total_pages=total,
                        content=f"> [页面处理失败: {str(e)}]",
                        content_type="vision_extracted",
                        source_file_type="pptx",
                        metadata={"filename": filename, "error": str(e)},
                        image_bytes=img_bytes,
                    )
                )
        return pages


class ImageHandler(BaseFileHandler):
    """图片文件处理：直接发送给 Vision LLM"""

    async def handle(self, file_stream: bytes, filename: str) -> list[ConvertedPage]:
        from PIL import Image

        # 统一转为 PNG
        img = Image.open(BytesIO(file_stream))
        buf = BytesIO()
        img.save(buf, format="PNG")
        png_bytes = buf.getvalue()

        ext = Path(filename).suffix.lstrip(".").lower() if filename else "png"

        logger.info(f"[ImageHandler] Processing image: {filename}")
        try:
            content = await _call_vision_llm(png_bytes, 1, context="图片")
        except Exception as e:
            logger.error(f"[ImageHandler] Failed: {e}")
            content = f"> [图片处理失败: {str(e)}]"

        return [
            ConvertedPage(
                page_number=1,
                total_pages=1,
                content=content,
                content_type="vision_extracted",
                source_file_type=ext,
                metadata={"filename": filename},
            )
        ]


class XlsxHandler(BaseFileHandler):
    """XLSX 文件处理：openpyxl 读取每个 Sheet → Markdown 表格"""

    async def handle(self, file_stream: bytes, filename: str) -> list[ConvertedPage]:
        from openpyxl import load_workbook

        wb = load_workbook(BytesIO(file_stream), read_only=True, data_only=True)
        pages = []
        total = len(wb.sheetnames)

        for idx, sheet_name in enumerate(wb.sheetnames, start=1):
            ws = wb[sheet_name]
            rows = list(ws.iter_rows(values_only=True))

            if not rows:
                content = f"(Sheet「{sheet_name}」为空)"
            else:
                content = self._rows_to_markdown(rows, sheet_name)

            pages.append(
                ConvertedPage(
                    page_number=idx,
                    total_pages=total,
                    content=content,
                    content_type="table_extracted",
                    source_file_type="xlsx",
                    metadata={"filename": filename, "sheet_name": sheet_name},
                )
            )

        wb.close()
        return pages

    def _rows_to_markdown(self, rows: list, sheet_name: str) -> str:
        """将行数据转为 Markdown 表格"""
        lines = [f"## {sheet_name}\n"]

        # 表头
        header = rows[0]
        header_cells = [str(cell) if cell is not None else "" for cell in header]
        lines.append("| " + " | ".join(header_cells) + " |")
        lines.append("| " + " | ".join(["---"] * len(header_cells)) + " |")

        # 数据行
        for row in rows[1:]:
            cells = [str(cell) if cell is not None else "" for cell in row]
            # 补齐列数
            while len(cells) < len(header_cells):
                cells.append("")
            lines.append("| " + " | ".join(cells[:len(header_cells)]) + " |")

        return "\n".join(lines)


class CsvHandler(BaseFileHandler):
    """CSV 文件处理：读取并转为 Markdown 表格"""

    async def handle(self, file_stream: bytes, filename: str) -> list[ConvertedPage]:
        # 尝试检测编码
        text = self._decode(file_stream)
        reader = csv.reader(text.splitlines())
        rows = list(reader)

        if not rows:
            content = "(CSV 文件为空)"
        else:
            content = self._rows_to_markdown(rows)

        return [
            ConvertedPage(
                page_number=1,
                total_pages=1,
                content=content,
                content_type="table_extracted",
                source_file_type="csv",
                metadata={"filename": filename},
            )
        ]

    def _decode(self, file_stream: bytes) -> str:
        """尝试多种编码解码"""
        for encoding in ("utf-8", "utf-8-sig", "gbk", "gb2312", "latin-1"):
            try:
                return file_stream.decode(encoding)
            except (UnicodeDecodeError, LookupError):
                continue
        return file_stream.decode("utf-8", errors="replace")

    def _rows_to_markdown(self, rows: list[list[str]]) -> str:
        """将 CSV 行转为 Markdown 表格"""
        lines = []
        header = rows[0]
        lines.append("| " + " | ".join(header) + " |")
        lines.append("| " + " | ".join(["---"] * len(header)) + " |")

        for row in rows[1:]:
            cells = row[:]
            while len(cells) < len(header):
                cells.append("")
            lines.append("| " + " | ".join(cells[:len(header)]) + " |")

        return "\n".join(lines)


class TextHandler(BaseFileHandler):
    """纯文本/Markdown 文件处理：直接读取内容"""

    async def handle(self, file_stream: bytes, filename: str) -> list[ConvertedPage]:
        # 尝试多种编码
        for encoding in ("utf-8", "utf-8-sig", "gbk", "latin-1"):
            try:
                content = file_stream.decode(encoding)
                break
            except (UnicodeDecodeError, LookupError):
                continue
        else:
            content = file_stream.decode("utf-8", errors="replace")

        ext = Path(filename).suffix.lstrip(".").lower() if filename else "txt"

        return [
            ConvertedPage(
                page_number=1,
                total_pages=1,
                content=content,
                content_type="text_extracted",
                source_file_type=ext,
                metadata={"filename": filename},
            )
        ]


# ============================================================
# Handler 注册表
# ============================================================

HANDLER_REGISTRY: dict[str, type[BaseFileHandler]] = {
    "docx": DocxHandler,
    "doc": DocxHandler,
    "pdf": PdfHandler,
    "pptx": PptxHandler,
    "ppt": PptxHandler,
    "png": ImageHandler,
    "jpg": ImageHandler,
    "jpeg": ImageHandler,
    "webp": ImageHandler,
    "bmp": ImageHandler,
    "xlsx": XlsxHandler,
    "xls": XlsxHandler,
    "csv": CsvHandler,
    "txt": TextHandler,
    "md": TextHandler,
    "markdown": TextHandler,
}


# ============================================================
# 主入口类
# ============================================================


class DocumentConverter:
    """通用文档转换器

    Usage:
        converter = DocumentConverter()
        pages = await converter.convert(file_bytes, "pptx", "presentation.pptx")
    """

    def get_supported_types(self) -> list[str]:
        """获取所有支持的文件类型"""
        return sorted(set(HANDLER_REGISTRY.keys()))

    def is_supported(self, file_type: str) -> bool:
        """判断文件类型是否受支持"""
        return file_type.lower().strip(".") in HANDLER_REGISTRY

    async def convert(
        self,
        file_stream: bytes,
        file_type: str,
        filename: str = "",
    ) -> list[ConvertedPage]:
        """将文件流转换为 ConvertedPage 列表

        Args:
            file_stream: 文件二进制流
            file_type: 文件扩展名（如 "docx"/"pdf"/"pptx"，不含点号）
            filename: 原始文件名（可选，用于日志和元数据）

        Returns:
            ConvertedPage 列表

        Raises:
            UnsupportedFileTypeError: 不支持的文件类型
            ConversionError: 转换过程中的错误
        """
        normalized_type = file_type.lower().strip(".")

        handler_cls = HANDLER_REGISTRY.get(normalized_type)
        if not handler_cls:
            raise UnsupportedFileTypeError(normalized_type)

        logger.info(
            f"[DocumentConverter] Converting: type={normalized_type}, "
            f"filename={filename}, size={len(file_stream)} bytes"
        )

        handler = handler_cls()
        pages = await handler.handle(file_stream, filename)

        logger.info(
            f"[DocumentConverter] Conversion complete: {len(pages)} pages extracted"
        )
        return pages

    def pages_to_markdown(self, pages: list[ConvertedPage], separator: str = "\n\n---\n\n") -> str:
        """将 ConvertedPage 列表拼接为完整 Markdown 文本

        Args:
            pages: ConvertedPage 列表
            separator: 页间分隔符

        Returns:
            完整 Markdown 字符串
        """
        parts = []
        for page in pages:
            if page.total_pages > 1:
                parts.append(f"# 第{page.page_number}页\n\n{page.content}")
            else:
                parts.append(page.content)
        return separator.join(parts)


# 模块级单例
document_converter = DocumentConverter()
