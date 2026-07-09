"""
火山引擎 OCR 服务（智能文档解析）

通过 volcengine SDK 的 ocr_pdf 接口，将 PDF 直接解析为 Markdown。

核心特性：
- 自适应 PDF 拆分策略（按 base64 大小选择批次页数：全量 → 10 → 5 → 2 → 1）
- 单页超大 PDF 自动压缩（JPEG + 降 DPI）后继续调 OCR API
- QPS=2 限流（Redis 分布式锁，跨 worker 互斥）
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
# 全局 OCR 互斥锁（Redis 分布式锁，跨 uvicorn worker 生效）
# 确保多进程部署时同时只有一个 OCR 请求
# ============================================================
_OCR_LOCK_KEY = "tx_agent:lock:ocr_global"
_OCR_LOCK_TTL = 300  # 锁过期时间（秒），防止死锁
_OCR_LOCK_POLL_INTERVAL = 1.0  # 等待锁时轮询间隔（秒）


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


def _split_pdf(pdf_bytes: bytes, pages_per_batch: int) -> list[tuple[bytes, int]]:
    """将 PDF 按页数拆分为多个子 PDF 字节。

    拆分后校验每个批次的实际 base64 大小，超限的批次自动递归再拆分，
    确保所有批次都满足 API 的 image_base64 大小限制。

    Args:
        pdf_bytes: 完整 PDF 文件字节
        pages_per_batch: 每批包含的页数

    Returns:
        子 PDF (字节, 页数) 元组列表。
        单页超限的批次标记为 page_count=0，表示需要压缩后重试 OCR。
    """
    import fitz  # PyMuPDF

    doc = fitz.open(stream=pdf_bytes, filetype="pdf")
    total_pages = len(doc)
    raw_batches: list[tuple[int, int, bytes]] = []  # (start_page, end_page, pdf_bytes)

    for start in range(0, total_pages, pages_per_batch):
        end = min(start + pages_per_batch, total_pages)
        batch_doc = fitz.open()  # 新建空文档
        batch_doc.insert_pdf(doc, from_page=start, to_page=end - 1)

        buf = BytesIO()
        batch_doc.save(buf)
        batch_bytes = buf.getvalue()
        batch_doc.close()

        raw_batches.append((start, end, batch_bytes))
        logger.info(
            f"[VolcOCR] PDF batch: pages {start + 1}-{end}/{total_pages}, "
            f"size={len(batch_bytes) / 1024:.1f}KB"
        )

    doc.close()

    # 校验每个批次的实际 base64 大小，超限则递归再拆分
    result: list[tuple[bytes, int]] = []
    for start, end, batch_bytes in raw_batches:
        b64_size = len(base64.b64encode(batch_bytes))
        page_count = end - start
        if b64_size <= _MAX_BASE64_SIZE:
            result.append((batch_bytes, page_count))
        else:
            if page_count <= 1:
                # 单页仍超限，标记 page_count=0 表示需要压缩后重试 OCR
                logger.warning(
                    f"[VolcOCR] 单页 base64={b64_size / 1024 / 1024:.2f}MB "
                    f"超限 (page {start + 1})，将压缩后重试 OCR"
                )
                result.append((batch_bytes, 0))  # page_count=0 → 压缩后重试 OCR
            else:
                # 递归拆分：页数减半
                half = max(1, page_count // 2)
                logger.warning(
                    f"[VolcOCR] 批次 pages {start + 1}-{end} "
                    f"base64={b64_size / 1024 / 1024:.2f}MB 超限，"
                    f"递归拆分为 {half} 页/批"
                )
                sub_batches = _split_pdf(batch_bytes, half)
                result.extend(sub_batches)

    return result


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

    - 通过 Redis 分布式锁确保跨 worker 同时只有 1 个请求
    - 失败时不修改数据，仅重试
    - 重试间隔指数退避

    Returns:
        该批次的 markdown 字符串
    """
    from app.core.redis import get_redis

    max_retries = settings.VOLC_OCR_MAX_RETRIES
    base_delay = settings.VOLC_OCR_RETRY_DELAY
    redis = get_redis()

    for attempt in range(1, max_retries + 1):
        # 阻塞等待获取 Redis 分布式锁
        token = None
        try:
            while True:
                token = await redis.set(
                    _OCR_LOCK_KEY, "1", nx=True, ex=_OCR_LOCK_TTL
                )
                if token:
                    break
                logger.debug(f"[VolcOCR] batch {batch_index} 等待 OCR 全局锁...")
                await asyncio.sleep(_OCR_LOCK_POLL_INTERVAL)

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
                    f"释放锁, {delay}s 后重试"
                )
                await asyncio.sleep(delay)
            else:
                logger.error(
                    f"[VolcOCR] batch {batch_index} 重试耗尽 "
                    f"({max_retries} attempts), 最后错误: {e}"
                )
                raise
        finally:
            # 释放 Redis 锁
            if token:
                await redis.delete(_OCR_LOCK_KEY)


def _compress_oversized_page(pdf_bytes: bytes, max_base64_mb: float = 7.5) -> bytes:
    """将超大的单页 PDF 压缩为更小的 PDF。

    策略：渲染为 JPEG 图片（逐步降低质量/DPI），嵌入新 PDF，
    确保 base64 编码后不超过 API 限制。

    Args:
        pdf_bytes: 包含单页的 PDF 字节
        max_base64_mb: 目标最大 base64 大小（MB），默认 7.5MB

    Returns:
        压缩后的单页 PDF 字节
    """
    import fitz  # PyMuPDF

    max_bytes = int(max_base64_mb * 1024 * 1024)

    doc = fitz.open(stream=pdf_bytes, filetype="pdf")
    page = doc[0]
    page_rect = page.rect  # 原始页面尺寸

    # 逐步尝试不同 DPI + JPEG 质量组合，直到 base64 大小达标
    configs = [
        (200, 85),
        (200, 60),
        (150, 70),
        (150, 50),
        (120, 50),
        (100, 40),
    ]

    compressed_pdf = None
    for dpi, jpeg_quality in configs:
        mat = fitz.Matrix(dpi / 72, dpi / 72)
        pix = page.get_pixmap(matrix=mat)

        # 渲染为 JPEG
        jpeg_bytes = pix.tobytes("jpeg", jpg_quality=jpeg_quality)

        # 创建新的单页 PDF，嵌入 JPEG 图片
        new_doc = fitz.open()
        new_page = new_doc.new_page(width=page_rect.width, height=page_rect.height)
        new_page.insert_image(new_page.rect, stream=jpeg_bytes)

        buf = BytesIO()
        new_doc.save(buf, garbage=4, deflate=True)
        new_doc.close()

        candidate = buf.getvalue()
        b64_size = len(base64.b64encode(candidate))

        if b64_size <= max_bytes:
            logger.info(
                f"[VolcOCR] 单页压缩成功: {len(pdf_bytes) / 1024:.0f}KB → "
                f"{len(candidate) / 1024:.0f}KB (base64={b64_size / 1024 / 1024:.2f}MB), "
                f"dpi={dpi}, jpeg_quality={jpeg_quality}"
            )
            compressed_pdf = candidate
            break
        else:
            logger.debug(
                f"[VolcOCR] 单页压缩尝试 dpi={dpi}, quality={jpeg_quality}: "
                f"base64={b64_size / 1024 / 1024:.2f}MB > {max_base64_mb}MB"
            )

    doc.close()

    if compressed_pdf is None:
        # 所有配置都不满足，用最后一档的结果（总比直接报错好）
        logger.warning(
            f"[VolcOCR] 单页压缩未达标，使用最低配置结果 "
            f"(base64={b64_size / 1024 / 1024:.2f}MB > {max_base64_mb}MB)"
        )
        compressed_pdf = candidate  # noqa: F821

    return compressed_pdf


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

    # 拆分 PDF（每个批次包含实际页数可能因递归拆分而不同）
    batches = _split_pdf(pdf_bytes, batch_size)
    logger.info(f"[VolcOCR] 共 {len(batches)} 个批次待处理")

    # 逐批处理（受 Semaphore 限流，严格串行）
    all_markdowns: list[str] = []
    page_offset = 0  # 累计页偏移，用于错误信息中的页码定位
    for i, (batch_bytes, batch_page_count) in enumerate(batches):
        try:
            if batch_page_count == 0:
                # 单页超大 PDF，压缩后继续调 OCR API
                logger.info(
                    f"[VolcOCR] batch {i + 1}: 单页超大，"
                    f"压缩后重试 OCR (page {page_offset + 1})"
                )
                compressed = _compress_oversized_page(batch_bytes)
                md = await _call_ocr_with_retry(
                    pdf_batch_bytes=compressed,
                    page_start=0,
                    page_num=1,
                    batch_index=i + 1,
                )
                all_markdowns.append(md)
                page_offset += 1
            else:
                md = await _call_ocr_with_retry(
                    pdf_batch_bytes=batch_bytes,
                    page_start=0,  # 子 PDF 从第 0 页开始
                    page_num=batch_page_count,
                    batch_index=i + 1,
                )
                all_markdowns.append(md)
                page_offset += batch_page_count
        except Exception as e:
            actual_pages = batch_page_count if batch_page_count > 0 else 1
            logger.error(f"[VolcOCR] batch {i + 1} 最终失败: {e}")
            # 失败的批次插入占位标记，不中断整体流程
            all_markdowns.append(
                f"\n\n> [OCR 识别失败: 第 {page_offset + 1}-{page_offset + actual_pages} 页, 错误: {e}]\n\n"
            )
            page_offset += actual_pages

    full_markdown = "\n\n".join(all_markdowns)
    logger.info(
        f"[VolcOCR] PDF 解析完成: total_pages={total_pages}, "
        f"batch_size={batch_size}, batches={len(batches)}, "
        f"markdown_len={len(full_markdown)}"
    )
    return full_markdown
