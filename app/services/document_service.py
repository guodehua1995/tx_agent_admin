"""文档关联数据清理服务 — 提供可复用的文档级联删除能力"""

import logging

from app.services.chunk_service import chunk_service

logger = logging.getLogger(__name__)


async def cleanup_document(document_id: int):
    """清理文档的所有关联数据：向量、切片结果、页面记录及截图文件

    适用于文档删除、合同删除等需要级联清理文档资源的场景。
    """
    from app.models.rag import DocumentPage, SlicingResult
    from app.services.extraction.base import BaseExtractor
    from app.services.file_storage import file_storage

    # 1. 清理向量数据
    await chunk_service.delete_by_doc_id(document_id)

    # 2. 清理切片结果
    deleted_slicing = await SlicingResult.filter(document_id=document_id).delete()
    if deleted_slicing:
        logger.info(f"Document cleanup: slicing records deleted doc_id={document_id} count={deleted_slicing}")

    # 3. 清理页面记录及截图
    pages = await DocumentPage.filter(document_id=document_id).all()
    for page in pages:
        if page.screenshot_url:
            try:
                await file_storage.delete(page.screenshot_url)
            except Exception as e:
                logger.warning(
                    f"Document cleanup: delete page screenshot failed doc_id={document_id} key={page.screenshot_url} error={e}"
                )

    # 前缀兜底清理
    try:
        await file_storage.delete_prefix(BaseExtractor.doc_screenshot_prefix(document_id))
    except Exception as e:
        logger.warning(
            f"Document cleanup: delete page prefix failed doc_id={document_id} error={e}"
        )

    deleted_pages = await DocumentPage.filter(document_id=document_id).delete()
    if deleted_pages:
        logger.info(f"Document cleanup: page records deleted doc_id={document_id} count={deleted_pages}")

    # 4. 软删除文档本身
    from app.models.rag import Document
    await Document.filter(id=document_id, is_deleted=False).update(is_deleted=True)
    logger.info(f"Document cleanup: soft deleted doc_id={document_id}")
