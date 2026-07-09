"""文档处理流水线补偿任务

扫描处于中间态的文档，通过 Redis 分布式锁协调后执行补偿。
"""

import asyncio
from datetime import datetime, timedelta

from tortoise.expressions import Q

from app.core.redis import get_redis
from app.core.redis_lock import LockKey
from app.log import logger
from app.models.enums import DocumentStatus
from app.models.rag import Document
from app.services.document_pipeline import document_pipeline
from app.settings import settings

# 中间态超时阈值（分钟）
STUCK_THRESHOLD_MINUTES = 30


async def _is_feishu_folder_managed(doc_id: int) -> bool:
    """检查 Document 是否正由飞书文件夹监听托管（设置了 FEISHU_FOLDER_INGEST 标记锁）。"""
    redis = get_redis()
    lock_key = f"{LockKey.FEISHU_FOLDER_INGEST}:{doc_id}"
    return bool(await redis.exists(lock_key))


async def compensate_pending_extract():
    """补偿 pending_extract 状态的文档：并发执行提取流程

    - 并发数由 settings.COMPENSATE_CONCURRENCY 控制，防止多文档同时提取压年事件循环
    - 并发互斥交由 document_pipeline.extract 内部的 Redis 锁保证
    - 飞书文件夹托管的文档（FEISHU_FOLDER_INGEST 标记锁）会跳过
    """
    docs = await Document.filter(
        status=DocumentStatus.PENDING_EXTRACT,
        is_deleted=False,
    ).all()

    if not docs:
        return

    logger.info(f"[Compensate] Found {len(docs)} pending_extract documents")

    # 过滤飞书文件夹托管的文档（限流 EXISTS 调用，避免 Redis 连接池耗尽）
    sem = asyncio.Semaphore(max(settings.COMPENSATE_CONCURRENCY * 2, 10))

    async def _check_managed(doc_id: int) -> bool:
        async with sem:
            return await _is_feishu_folder_managed(doc_id)

    managed = await asyncio.gather(*[_check_managed(d.id) for d in docs])
    candidates = [d for d, is_managed in zip(docs, managed) if not is_managed]

    skipped = len(docs) - len(candidates)
    if skipped:
        logger.debug(f"[Compensate] Skipped {skipped} feishu-managed pending_extract docs")
    if not candidates:
        return

    logger.info(f"[Compensate] Compensating {len(candidates)} pending_extract docs (concurrency={settings.COMPENSATE_CONCURRENCY})")

    sem = asyncio.Semaphore(settings.COMPENSATE_CONCURRENCY)

    async def _run_one_extract(doc: Document):
        async with sem:
            try:
                logger.info(f"[Compensate] Processing pending_extract: doc_id={doc.id}")
                await document_pipeline.extract(doc.id)
            except Exception:
                logger.exception(f"[Compensate] extract failed: doc_id={doc.id}")

    await asyncio.gather(*[_run_one_extract(d) for d in candidates])


async def compensate_approved():
    """补偿 approved 状态的文档：并发执行切片+向量化

    - 并发数由 settings.COMPENSATE_CONCURRENCY 控制
    - 并发互斥交由 document_pipeline.vectorize 内部的 Redis 锁保证
    - 飞书文件夹托管的文档（auto_approve 路径）同样跳过
    """
    docs = await Document.filter(
        status=DocumentStatus.APPROVED,
        is_deleted=False,
    ).all()

    if not docs:
        return

    logger.info(f"[Compensate] Found {len(docs)} approved documents")

    # 过滤飞书文件夹托管的文档（限流 EXISTS 调用，避免 Redis 连接池耗尽）
    sem = asyncio.Semaphore(max(settings.COMPENSATE_CONCURRENCY * 2, 10))

    async def _check_managed(doc_id: int) -> bool:
        async with sem:
            return await _is_feishu_folder_managed(doc_id)

    managed = await asyncio.gather(*[_check_managed(d.id) for d in docs])
    candidates = [d for d, is_managed in zip(docs, managed) if not is_managed]

    skipped = len(docs) - len(candidates)
    if skipped:
        logger.debug(f"[Compensate] Skipped {skipped} feishu-managed approved docs")
    if not candidates:
        return

    logger.info(f"[Compensate] Compensating {len(candidates)} approved docs (concurrency={settings.COMPENSATE_CONCURRENCY})")

    sem = asyncio.Semaphore(settings.COMPENSATE_CONCURRENCY)

    async def _run_one_vectorize(doc: Document):
        async with sem:
            try:
                logger.info(f"[Compensate] Vectorizing approved: doc_id={doc.id}")
                await document_pipeline.vectorize(doc.id)
            except Exception:
                logger.exception(f"[Compensate] vectorize failed: doc_id={doc.id}")

    await asyncio.gather(*[_run_one_vectorize(d) for d in candidates])


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
