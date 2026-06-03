"""飞书云盘文件夹扫描服务

定时扫描配置的文件夹，发现新增文件 → 自动创建 Document 并触发处理流水线。
幂等锚为 feishu_folder_file (folder_watch_id, file_token) 唯一索引。
"""

import asyncio
from datetime import datetime
from pathlib import Path

from app.core.redis_lock import LockKey, RedisLock
from app.log import logger
from app.models.enums import DocumentSourceType, DocumentStatus, DocumentTypeCode
from app.models.rag import (
    Document,
    FeishuFolderFile,
    FeishuFolderWatch,
    KnowledgeBase,
)
from app.services.document_pipeline import document_pipeline
from app.services.extraction.base import CONVERTIBLE_EXTENSIONS
from app.services.feishu_service import feishu_service
from app.settings import settings

# 飞书侧 type 字段中需要直接跳过的（一期）
_SKIP_TYPES = {"folder", "shortcut"}


class FeishuFolderScanService:
    """飞书云盘文件夹扫描服务（单例）。"""

    # 单 watch 单次扫描最长允许时间（秒），防止锁泄漏 / 异常长任务挂死调度循环
    _SCAN_LOCK_TTL = 600

    async def scan_all(self) -> None:
        """主入口：扫描所有启用的 watch。

        - 每个 watch 独立 Redis 锁互斥（多实例 / 重叠周期下不并发）；
        - 单 watch 失败不影响其它 watch；
        - 按 watch.scan_interval_seconds 决定本轮是否要跑（避免每次调度都拉接口）。
        """
        if not settings.FEISHU_FOLDER_SCAN_ENABLED:
            return

        watches = await FeishuFolderWatch.filter(is_active=True, is_deleted=False).all()
        if not watches:
            return

        logger.info(f"[FeishuFolderScan] {len(watches)} active watches")

        for watch in watches:
            if not self._should_scan_now(watch):
                continue
            try:
                await self._scan_one(watch)
            except Exception:
                logger.exception(
                    f"[FeishuFolderScan] watch scan failed: id={watch.id}, name={watch.name}"
                )

    async def scan_one_now(self, watch_id: int) -> None:
        """手动触发一次扫描（API 立即扫描使用），同样走锁。"""
        watch = await FeishuFolderWatch.get(id=watch_id)
        if watch.is_deleted:
            raise ValueError("文件夹监听已删除")
        await self._scan_one(watch)

    def _should_scan_now(self, watch: FeishuFolderWatch) -> bool:
        if not watch.last_scanned_at:
            return True
        interval = watch.scan_interval_seconds or settings.FEISHU_FOLDER_SCAN_DEFAULT_INTERVAL
        elapsed = (datetime.now() - watch.last_scanned_at.replace(tzinfo=None)).total_seconds()
        return elapsed >= interval

    async def _scan_one(self, watch: FeishuFolderWatch) -> None:
        lock = RedisLock()
        lock_key = f"{LockKey.FEISHU_FOLDER_SCAN}:{watch.id}"
        token = await lock.acquire(lock_key, ttl=self._SCAN_LOCK_TTL)
        if not token:
            logger.info(f"[FeishuFolderScan] skipped (locked): watch_id={watch.id}")
            return

        try:
            watch.last_scan_status = "running"
            watch.last_error = None
            await watch.save()

            access_token = await feishu_service.get_tenant_access_token(
                settings.FEISHU_DOC_BOT_APPID, settings.FEISHU_DOC_BOT_APPSECRET
            )
            files = await feishu_service.list_files_in_folder(
                folder_token=watch.folder_token,
                access_token=access_token,
                max_files=settings.FEISHU_FOLDER_SCAN_MAX_FILES_PER_FOLDER,
            )
            logger.info(
                f"[FeishuFolderScan] watch_id={watch.id} fetched {len(files)} files"
            )

            new_files = await self._diff_new_files(watch, files)
            ingested = await self._ingest_new_files(watch, new_files)

            watch.last_scanned_at = datetime.now()
            watch.last_scan_status = "success"
            watch.last_error = None
            await watch.save()

            logger.info(
                f"[FeishuFolderScan] watch_id={watch.id} done: "
                f"new={len(new_files)}, ingested={ingested}"
            )
        except Exception as e:
            logger.exception(f"[FeishuFolderScan] watch_id={watch.id} error")
            watch.last_scan_status = "failed"
            watch.last_error = str(e)[:1000]
            watch.last_scanned_at = datetime.now()
            await watch.save()
        finally:
            await lock.release(lock_key, token)

    async def _diff_new_files(
        self, watch: FeishuFolderWatch, files: list[dict]
    ) -> list[dict]:
        """与已登记 token 集合做 diff，返回需要新入库的文件列表。

        过滤掉文件夹/快捷方式等不可入库类型。
        """
        candidates = [f for f in files if f.get("type") not in _SKIP_TYPES and f.get("token")]
        if not candidates:
            return []

        existing = await FeishuFolderFile.filter(
            folder_watch_id=watch.id,
            file_token__in=[f["token"] for f in candidates],
        ).values_list("file_token", flat=True)
        existing_set = set(existing)

        return [f for f in candidates if f["token"] not in existing_set]

    async def _ingest_new_files(
        self, watch: FeishuFolderWatch, new_files: list[dict]
    ) -> int:
        """逐文件登记 + 创建 Document + 触发 pipeline。

        - 单文件失败 → ingest_status=failed，不影响其它文件；
        - 单轮入队上限由 settings.FEISHU_FOLDER_SCAN_BATCH_LIMIT 控制；
        - 不支持类型直接登记 skipped，避免下轮重复探测。
        """
        if not new_files:
            return 0

        batch_limit = settings.FEISHU_FOLDER_SCAN_BATCH_LIMIT
        batch = new_files[:batch_limit]
        if len(new_files) > batch_limit:
            logger.info(
                f"[FeishuFolderScan] watch_id={watch.id} batch truncated: "
                f"{len(new_files)} → {batch_limit}"
            )

        ingested = 0
        for f in batch:
            try:
                if await self._ingest_one(watch, f):
                    ingested += 1
            except Exception as e:
                logger.exception(
                    f"[FeishuFolderScan] ingest failed: watch_id={watch.id}, "
                    f"token={f.get('token')}"
                )
                # 兜底登记 failed，避免下轮重复尝试
                await FeishuFolderFile.update_or_create(
                    folder_watch_id=watch.id,
                    file_token=f.get("token") or "",
                    defaults={
                        "file_name": f.get("name") or "",
                        "file_type": f.get("type") or "",
                        "ingest_status": "failed",
                        "ingest_error": str(e)[:1000],
                    },
                )
        return ingested

    async def _ingest_one(self, watch: FeishuFolderWatch, file_meta: dict) -> bool:
        """单文件入库。返回 True 表示成功创建 Document。"""
        file_token = file_meta["token"]
        file_name = file_meta.get("name") or file_token
        file_type = file_meta.get("type") or ""
        modified_time = file_meta.get("modified_time")

        # 1. 登记 pending（先占位，确保幂等锚立即生效）
        record, _ = await FeishuFolderFile.update_or_create(
            folder_watch_id=watch.id,
            file_token=file_token,
            defaults={
                "file_name": file_name,
                "file_type": file_type,
                "feishu_modified_time": int(modified_time) if modified_time else None,
                "ingest_status": "pending",
                "ingest_error": None,
            },
        )

        # 2. 类型预检：跳过不支持的扩展（一期保守策略）
        skip_reason = self._unsupported_reason(watch.doc_type_code, file_type, file_name)
        if skip_reason:
            record.ingest_status = "skipped"
            record.ingest_error = skip_reason
            await record.save()
            logger.info(
                f"[FeishuFolderScan] skipped: watch_id={watch.id}, token={file_token}, "
                f"reason={skip_reason}"
            )
            return False

        # 3. 构造 Document.source_meta：复用 feishu_doc 来源 + 伪造 URL，
        #    后续 BaseExtractor._fetch_file_bytes 通过 parse_feishu_url 走原有路径
        feishu_url = f"https://feishu.cn/{file_type or 'file'}/{file_token}"
        source_meta = {
            "feishu_url": feishu_url,
            "feishu_file_token": file_token,
            "feishu_file_type": file_type,
            "filename": file_name,
            "folder_watch_id": watch.id,
            "auto_ingested": True,
        }

        doc = await Document.create(
            title=file_name,
            source_type=DocumentSourceType.FEISHU_DOC,
            source_meta=source_meta,
            doc_type_code=watch.doc_type_code,
            knowledge_base_id=watch.knowledge_base_id,
            status=DocumentStatus.PENDING_EXTRACT,
            uploader_id=0,  # 0 表示系统自动入库
        )

        record.document_id = doc.id
        record.ingest_status = "ingested"
        record.ingest_error = None
        await record.save()

        # 4. 异步触发提取流水线，不等待结果（与 HTTP create 路径行为一致）
        asyncio.create_task(document_pipeline.process_document(doc.id))

        logger.info(
            f"[FeishuFolderScan] ingested: watch_id={watch.id}, token={file_token}, "
            f"doc_id={doc.id}, type_code={watch.doc_type_code}"
        )
        return True

    def _unsupported_reason(
        self, doc_type_code: str, file_type: str, file_name: str
    ) -> str | None:
        """判断该文件是否不适合走给定 doc_type_code 的处理器。

        feishu_doc：飞书原生文档（docx/wiki/sheet）；
        ppt / contract：必须是 file 类型且扩展名在 CONVERTIBLE_EXTENSIONS 内。
        """
        if doc_type_code == DocumentTypeCode.FEISHU_DOC:
            if file_type not in {"docx", "doc", "sheet", "wiki"}:
                return f"feishu_doc 仅支持 docx/sheet/wiki 类型，当前: {file_type}"
            return None

        # 二进制文件类型：必须是 file 且扩展名可转换
        if file_type != "file":
            return f"{doc_type_code} 仅支持 file 类型(可下载文件)，当前: {file_type}"
        ext = Path(file_name).suffix.lstrip(".").lower()
        if ext not in CONVERTIBLE_EXTENSIONS:
            return f"{doc_type_code} 不支持的扩展名: .{ext}"
        return None


feishu_folder_scan_service = FeishuFolderScanService()
