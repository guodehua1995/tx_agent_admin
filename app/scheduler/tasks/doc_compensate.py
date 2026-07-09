"""文档处理流水线补偿任务

扫描处于中间态的文档，通过 Redis 分布式锁协调后执行补偿。
所有补偿任务串行执行，避免 OCR 服务并发冲突。
"""

from datetime import datetime, timedelta

from tortoise.expressions import Q

from app.core.redis import get_redis
from app.core.redis_lock import LockKey
from app.log import logger
from app.models.enums import DocumentStatus
from app.models.rag import Document, FeishuFolderWatch
from app.services.document_pipeline import document_pipeline

# 中间态超时阈值（分钟）
STUCK_THRESHOLD_MINUTES = 30


async def _is_feishu_folder_managed(doc_id: int) -> bool:
    """检查 Document 是否正由飞书文件夹监听托管（设置了 FEISHU_FOLDER_INGEST 标记锁）。"""
    redis = get_redis()
    lock_key = f"{LockKey.FEISHU_FOLDER_INGEST}:{doc_id}"
    return bool(await redis.exists(lock_key))


async def _should_auto_approve(doc: Document) -> bool:
    """检查文档是否属于启用了自动审批的文件夹监听。

    通过 source_meta.folder_watch_id 查找对应的 FeishuFolderWatch，
    返回其 auto_approve 配置。
    """
    source_meta = doc.source_meta or {}
    if not source_meta.get("auto_ingested"):
        return False
    watch_id = source_meta.get("folder_watch_id")
    if not watch_id:
        return False
    watch = await FeishuFolderWatch.get_or_none(id=watch_id)
    if watch is None:
        return False
    return watch.auto_approve


async def compensate_pending_extract():
    """补偿 pending_extract 状态的文档：串行执行提取流程

    - OCR 服务 QPS 有限，多文档并行会导致大量重试失败
    - 因此改为串行：逐个处理，前一个完成后再处理下一个
    - 飞书文件夹托管的文档（FEISHU_FOLDER_INGEST 标记锁）会跳过
    """
    docs = await Document.filter(
        status=DocumentStatus.PENDING_EXTRACT,
        is_deleted=False,
    ).all()

    if not docs:
        return

    logger.info(f"[Compensate] Found {len(docs)} pending_extract documents")

    # 过滤飞书文件夹托管的文档
    candidates = []
    for d in docs:
        if not await _is_feishu_folder_managed(d.id):
            candidates.append(d)

    skipped = len(docs) - len(candidates)
    if skipped:
        logger.debug(f"[Compensate] Skipped {skipped} feishu-managed pending_extract docs")
    if not candidates:
        return

    logger.info(f"[Compensate] Compensating {len(candidates)} pending_extract docs (serial)")

    # 串行执行：逐个处理，避免 OCR 并发冲突
    for doc in candidates:
        try:
            logger.info(f"[Compensate] Processing pending_extract: doc_id={doc.id}")
            await document_pipeline.extract(doc.id)

            # 重新加载文档状态：extract 可能因 Redis 锁被占用而静默跳过
            await doc.refresh_from_db()
            if doc.status != DocumentStatus.PENDING_REVIEW:
                logger.info(
                    f"[Compensate] extract did not advance status, "
                    f"skip auto-approve: doc_id={doc.id}, status={doc.status}"
                )
                continue

            # 提取成功后检查是否需要自动审批
            if await _should_auto_approve(doc):
                logger.info(
                    f"[Compensate] Auto-approving: doc_id={doc.id} "
                    f"(folder_watch_id={doc.source_meta.get('folder_watch_id')})"
                )
                await document_pipeline.approve(doc.id)
        except Exception:
            logger.exception(f"[Compensate] extract failed: doc_id={doc.id}")


async def compensate_approved():
    """补偿 approved 状态的文档：串行执行切片+向量化

    - OCR 服务 QPS 有限，多文档并行会导致大量重试失败
    - 因此改为串行：逐个处理，前一个完成后再处理下一个
    - 飞书文件夹托管的文档（auto_approve 路径）同样跳过
    """
    docs = await Document.filter(
        status=DocumentStatus.APPROVED,
        is_deleted=False,
    ).all()

    if not docs:
        return

    logger.info(f"[Compensate] Found {len(docs)} approved documents")

    # 过滤飞书文件夹托管的文档
    candidates = []
    for d in docs:
        if not await _is_feishu_folder_managed(d.id):
            candidates.append(d)

    skipped = len(docs) - len(candidates)
    if skipped:
        logger.debug(f"[Compensate] Skipped {skipped} feishu-managed approved docs")
    if not candidates:
        return

    logger.info(f"[Compensate] Compensating {len(candidates)} approved docs (serial)")

    # 串行执行：逐个处理
    for doc in candidates:
        try:
            logger.info(f"[Compensate] Vectorizing approved: doc_id={doc.id}")
            await document_pipeline.vectorize(doc.id)
        except Exception:
            logger.exception(f"[Compensate] vectorize failed: doc_id={doc.id}")


async def reset_stuck_documents():
    """重置卡在 slicing/vectorizing 中间态超过阈值的文档

    这些文档可能是处理进程意外中断（如服务器重启）导致的，
    重置为 approved 后下一轮调度器会自动补偿。

    并发安全：重置前检查向量化锁是否还在。锁还在说明任务真的在跑（
    不是卡住），不应重置，避免与在跑任务产生并发。
    """
    threshold = datetime.now() - timedelta(minutes=STUCK_THRESHOLD_MINUTES)
    stuck_statuses = [DocumentStatus.SLICING, DocumentStatus.VECTORIZING]

    docs = await Document.filter(
        Q(status__in=stuck_statuses) & Q(updated_at__lt=threshold) & Q(is_deleted=False)
    ).all()

    if not docs:
        return

    logger.info(f"[Compensate] Found {len(docs)} stuck documents (>{STUCK_THRESHOLD_MINUTES}min)")

    redis = get_redis()
    for doc in docs:
        # 如果向量化锁还在，说明任务仍在执行（锁 TTL 已调到 1800s），不要重置
        lock_key = f"{LockKey.DOCUMENT_VECTORIZE}:{doc.id}"
        if await redis.exists(lock_key):
            logger.debug(f"[Compensate] Vectorize lock alive, skip reset: doc_id={doc.id}")
            continue

        old_status = doc.status
        doc.status = DocumentStatus.APPROVED
        await doc.save()
        logger.info(
            f"[Compensate] Reset stuck: doc_id={doc.id}, "
            f"{old_status} -> approved"
        )
