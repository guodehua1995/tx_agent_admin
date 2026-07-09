"""
火山引擎 OCR 服务（智能文档解析）

通过 volcengine SDK 的 ocr_pdf 接口，将 PDF 直接解析为 Markdown。

核心特性：
- 自适应 PDF 拆分策略（按 base64 大小选择批次页数：全量 → 10 → 5 → 2 → 1）
- QPS=2 限流（asyncio.Semaphore 全局锁）
- 失败自动重试（不修改数据，仅重试）
- 多线程安全

文档: https://www.volcengine.com/docs/86081/1804817
"""

import asyncio
import base64
from io import BytesIO

from app.log import logger
from app.settings import settings

# ============================================================
# 全局 QPS 限流器：最多 2 个并发请求
# ============================================================
_ocr_semaphore = asyncio.Semaphore(2)


def _get_volc_credentials() -> tuple[str, str]:
    """获取火山引擎 AK/SK"""
    ak = settings.VOLC_AK
    sk = settings.VOLC_SK
    if not ak or not sk:
        raise RuntimeError(
            "火山引擎 OCR 凭证未配置，请在 .env 中设置 VOLC_AK 和 VOLC_SK"
        )
    return ak, sk


# OCR API 限制 base64 大小（5MB），超过则需拆分
_MAX_BASE64_SIZE = 5 * 1024 * 1024  # 5MB

# 自适应拆分档位：从大到小尝试，找到合适的每批页数
_SPLIT_TIERS = [10, 5, 2, 1]


def _split_pdf(pdf_bytes: bytes, pages_per_batch: int) -> list[bytes]:
    """将 PDF 按页数拆分为多个子 PDF 字节。

    Args:
        pdf_bytes: 完整 PDF 文件字节
        pages_per_batch: 每批包含的页数

    Returns:
        子 PDF 字节列表
    """
    import fitz  # PyMuPDF

    doc = fitz.open(stream=pdf_bytes, filetype="pdf")
    total_pages = len(doc)
    batches = []

    for start in range(0, total_pages, pages_per_batch):
        end = min(start + pages_per_batch, total_pages)
        batch_doc = fitz.open()  # 新建空文档
        batch_doc.insert_pdf(doc, from_page=start, to_page=end - 1)

        buf = BytesIO()
        batch_doc.save(buf)
        batches.append(buf.getvalue())
        batch_doc.close()

        logger.info(
            f"[VolcOCR] PDF batch: pages {start + 1}-{end}/{total_pages}, "
            f"size={len(buf.getvalue()) / 1024:.1f}KB"
        )

    doc.close()
    return batches


def _determine_batch_size(pdf_bytes: bytes, total_pages: int) -> int:
    """根据 PDF 的 base64 大小自适应选择每批页数。

    策略：
    - base64 < 5MB → 不拆分（返回 total_pages，整份发送）
    - base64 >= 5MB → 依次尝试 10页/5页/2页/1页 每批
    - 若总页数不足当前档位，自动下降到下一档

    Returns:
        每批页数
    """
    b64_size = len(base64.b64encode(pdf_bytes))

    if b64_size < _MAX_BASE64_SIZE:
        logger.info(
            f"[VolcOCR] PDF base64={b64_size / 1024 / 1024:.2f}MB < 5MB, "
            f"整份发送不拆分"
        )
        return total_pages  # 整份发送

    # 需要拆分，从大档到小档尝试
    for tier in _SPLIT_TIERS:
        if total_pages <= tier:
            # 总页数不足这一档，下降到下一档
            continue
        # 估算：按总大小等比缩放到每批
        estimated_batch_b64 = b64_size * tier / total_pages
        if estimated_batch_b64 < _MAX_BASE64_SIZE:
            logger.info(
                f"[VolcOCR] PDF base64={b64_size / 1024 / 1024:.2f}MB, "
                f"total_pages={total_pages}, 选择 batch_size={tier}"
            )
            return tier

    # 所有档位都不满足（或总页数很少），兜底单页
    logger.warning(
        f"[VolcOCR] PDF base64={b64_size / 1024 / 1024:.2f}MB, "
        f"total_pages={total_pages}, 所有档位均超限, 兜底 batch_size=1"
    )
    return 1


def _call_ocr_pdf_sync(pdf_batch_bytes: bytes, page_start: int, page_num: int) -> dict:
    """同步调用火山引擎 ocr_pdf API（在线程池中运行）。

    Args:
        pdf_batch_bytes: 单批 PDF 字节
        page_start: 起始页码（从 0 开始）
        page_num: 解析页数

    Returns:
        API 响应 dict
    """
    from volcengine.visual.VisualService import VisualService

    ak, sk = _get_volc_credentials()

    visual_service = VisualService()
    visual_service.set_ak(ak)
    visual_service.set_sk(sk)

    base64_data = base64.b64encode(pdf_batch_bytes).decode("utf-8")

    form = {
        "image_base64": base64_data,
        "image_url": "",
        "version": "v3",
        "page_start": page_start,
        "page_num": page_num,
        "table_mode": "html",
        "filter_header": "true",
    }

    resp = visual_service.ocr_pdf(form)
    return resp


async def _call_ocr_with_retry(
    pdf_batch_bytes: bytes,
    page_start: int,
    page_num: int,
    batch_index: int,
) -> str:
    """带限流和重试的 OCR 调用。

    - 通过 Semaphore 限制最多 2 个并发
    - 失败时不修改数据，仅重试
    - 重试间隔指数退避

    Returns:
        该批次的 markdown 字符串
    """
    max_retries = settings.VOLC_OCR_MAX_RETRIES
    base_delay = settings.VOLC_OCR_RETRY_DELAY

    for attempt in range(1, max_retries + 1):
        # 仅在 API 调用瞬间持有信号量，重试等待时释放
        async with _ocr_semaphore:
            try:
                resp = await asyncio.get_event_loop().run_in_executor(
                    None,
                    _call_ocr_pdf_sync,
                    pdf_batch_bytes,
                    page_start,
                    page_num,
                )

                # 检查响应
                if not resp or resp.get("code") != 10000:
                    error_msg = resp.get("message", "unknown error") if resp else "empty response"
                    raise RuntimeError(
                        f"OCR API 返回错误: code={resp.get('code') if resp else 'N/A'}, "
                        f"message={error_msg}"
                    )

                data = resp.get("data")
                if not data:
                    raise RuntimeError("OCR API 返回 data 为空")

                markdown = data.get("markdown", "")
                if not markdown:
                    logger.warning(
                        f"[VolcOCR] batch {batch_index}: OCR 返回空 markdown，"
                        f"可能该页无文字内容"
                    )

                logger.info(
                    f"[VolcOCR] batch {batch_index} 成功: "
                    f"pages={page_start + 1}-{page_start + page_num}, "
                    f"markdown_len={len(markdown)}"
                )
                return markdown

            except Exception as e:
                if attempt < max_retries:
                    delay = base_delay * (2 ** (attempt - 1))
                    logger.warning(
                        f"[VolcOCR] batch {batch_index} 失败 "
                        f"(attempt {attempt}/{max_retries}): {e}, "
                        f"释放信号量, {delay}s 后重试"
                    )
                    # 信号量在 except 退出 async with 时自动释放
                    await asyncio.sleep(delay)
                else:
                    logger.error(
                        f"[VolcOCR] batch {batch_index} 重试耗尽 "
                        f"({max_retries} attempts), 最后错误: {e}"
                    )
                    raise


async def ocr_pdf_to_markdown(pdf_bytes: bytes) -> str:
    """将 PDF 通过火山引擎 OCR 解析为 Markdown。

    流程：
    1. 用 PyMuPDF 获取总页数
    2. 按 base64 大小自适应选择拆分档位（全量 → 10 → 5 → 2 → 1 页/批）
    3. 拆分后每批调用 ocr_pdf API（限流 QPS=2 + 失败重试）
    4. 拼接所有批次的 markdown

    Args:
        pdf_bytes: 完整 PDF 文件字节

    Returns:
        完整 Markdown 字符串
    """
    import fitz  # PyMuPDF

    # 获取总页数
    doc = fitz.open(stream=pdf_bytes, filetype="pdf")
    total_pages = len(doc)
    doc.close()

    if total_pages == 0:
        raise ValueError("PDF 文件没有任何页面")

    # 自适应确定每批页数
    batch_size = _determine_batch_size(pdf_bytes, total_pages)

    logger.info(
        f"[VolcOCR] 开始解析 PDF: total_pages={total_pages}, "
        f"batch_size={batch_size}, file_size={len(pdf_bytes) / 1024:.1f}KB"
    )

    # 拆分 PDF
    batches = _split_pdf(pdf_bytes, batch_size)
    logger.info(f"[VolcOCR] 共 {len(batches)} 个批次待处理")

    # 逐批处理（受 Semaphore 限流，不会超过 2 并发）
    all_markdowns: list[str] = []
    for i, batch_bytes in enumerate(batches):
        page_start = i * batch_size
        page_num = min(batch_size, total_pages - page_start)

        try:
            md = await _call_ocr_with_retry(
                pdf_batch_bytes=batch_bytes,
                page_start=0,  # 子 PDF 从第 0 页开始
                page_num=page_num,
                batch_index=i + 1,
            )
            all_markdowns.append(md)
        except Exception as e:
            logger.error(f"[VolcOCR] batch {i + 1} 最终失败: {e}")
            # 失败的批次插入占位标记，不中断整体流程
            all_markdowns.append(
                f"\n\n> [OCR 识别失败: 第 {page_start + 1}-{page_start + page_num} 页, 错误: {e}]\n\n"
            )

    full_markdown = "\n\n".join(all_markdowns)
    logger.info(
        f"[VolcOCR] PDF 解析完成: total_pages={total_pages}, "
        f"batch_size={batch_size}, batches={len(batches)}, "
        f"markdown_len={len(full_markdown)}"
    )
    return full_markdown
