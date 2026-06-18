"""飞书云盘文件夹扫描服务

定时扫描配置的文件夹，发现新增文件 → 自动创建 Document 并触发处理流水线。
幂等锚为 feishu_folder_file (folder_watch_id, file_token) 唯一索引。
支持：自动审批旁路、文件变更感知、子文件夹递归、access_token 缓存、并发扫描。
"""

import asyncio
import time
from datetime import datetime
from pathlib import Path

from app.core.redis import get_redis
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
_SKIP_TYPES = {"shortcut"}

# tenant_access_token 缓存（进程内，避免每次扫描都请求飞书 API）
_token_cache: dict[str, tuple[str, float]] = {}  # {app_id: (token, expire_time)}
_TOKEN_TTL = 5400  # 飞书 token 有效期 7200s，提前 1800s 刷新


class FeishuFolderScanService:
    """飞书云盘文件夹扫描服务（单例）。"""

    # 单 watch 单次扫描最长允许时间（秒），防止锁泄漏 / 异常长任务挂死调度循环
    _SCAN_LOCK_TTL = 600

    async def scan_all(self) -> None:
        """主入口：扫描所有启用的 watch。

        - 每个 watch 独立 Redis 锁互斥（多实例 / 重叠周期下不并发）；
        - 单 watch 失败不影响其它 watch；
        - 按 watch.scan_interval_seconds 决定本轮是否要跑（避免每次调度都拉接口）；
        - 使用 asyncio.gather 并发扫描多个 watch，提高吞吐。
        """
        if not settings.FEISHU_FOLDER_SCAN_ENABLED:
            return

        watches = await FeishuFolderWatch.filter(is_active=True, is_deleted=False).all()
        if not watches:
            return

        logger.info(f"[FeishuFolderScan] {len(watches)} active watches")

        due_watches = [w for w in watches if self._should_scan_now(w)]
        if not due_watches:
            return

        results = await asyncio.gather(
            *[self._scan_one_safe(w) for w in due_watches],
            return_exceptions=True,
        )
        for w, r in zip(due_watches, results):
            if isinstance(r, Exception):
                logger.exception(
                    f"[FeishuFolderScan] watch scan failed: id={w.id}, name={w.name}"
                )

    async def _scan_one_safe(self, watch: FeishuFolderWatch) -> None:
        """带异常兜底的 scan_one，供 gather 使用。"""
        await self._scan_one(watch)

    async def scan_one_now(self, watch_id: int) -> None:
        """手动触发一次扫描（API 立即扫描使用），同样走锁。"""
        watch = await FeishuFolderWatch.get(id=watch_id)
        if watch.is_deleted:
            raise ValueError("文件夹监听已删除")
        if not watch.is_active:
            raise ValueError("文件夹监听已禁用")
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

            access_token = await self._get_access_token()
            files = await self._collect_all_files(
                watch, access_token,
                max_files=settings.FEISHU_FOLDER_SCAN_MAX_FILES_PER_FOLDER,
            )
            logger.info(
                f"[FeishuFolderScan] watch_id={watch.id} fetched {len(files)} files"
            )

            new_files, updated_files = await self._diff_new_and_updated(watch, files)
            deleted_count = await self._detect_deleted_files(watch, files)
            ingested = await self._ingest_new_files(watch, new_files)
            re_ingested = await self._re_ingest_updated_files(watch, updated_files)

            watch.last_scanned_at = datetime.now()
            watch.last_scan_status = "success"
            watch.last_error = None
            await watch.save()

            logger.info(
                f"[FeishuFolderScan] watch_id={watch.id} done: "
                f"new={len(new_files)}, ingested={ingested}, "
                f"updated={len(updated_files)}, re_ingested={re_ingested}, "
                f"feishu_deleted={deleted_count}"
            )
        except Exception as e:
            logger.exception(f"[FeishuFolderScan] watch_id={watch.id} error")
            watch.last_scan_status = "failed"
            watch.last_error = str(e)[:1000]
            watch.last_scanned_at = datetime.now()
            await watch.save()
        finally:
            await lock.release(lock_key, token)

    async def _diff_new_and_updated(
        self, watch: FeishuFolderWatch, files: list[dict]
    ) -> tuple[list[dict], list[dict]]:
        """与已登记 token 集合做 diff，返回 (新增文件, 变更文件)。

        过滤掉快捷方式等不可入库类型。
        变更判断：已入库文件且 feishu_modified_time 发生变化。
        """
        candidates = [f for f in files if f.get("type") not in _SKIP_TYPES and f.get("token")]
        if not candidates:
            return [], []

        existing_records = await FeishuFolderFile.filter(
            folder_watch_id=watch.id,
            file_token__in=[f["token"] for f in candidates],
        )
        existing_map = {r.file_token: r for r in existing_records}

        new_files = []
        updated_files = []
        for f in candidates:
            ft = f["token"]
            if ft not in existing_map:
                new_files.append(f)
            else:
                # 检查是否有变更（仅 ingested 状态的文件才触发更新）
                record = existing_map[ft]
                new_mtime = f.get("modified_time")
                if (
                    record.ingest_status == "ingested"
                    and new_mtime is not None
                    and record.feishu_modified_time is not None
                    and int(new_mtime) != record.feishu_modified_time
                ):
                    updated_files.append(f)

        return new_files, updated_files

    async def _detect_deleted_files(
        self, watch: FeishuFolderWatch, files: list[dict]
    ) -> int:
        """检测飞书侧已删除的文件：已登记但不在飞书返回列表中的文件。

        将 ingest_status 标记为 feishu_deleted，不自动清理，等人工确认。
        """
        feishu_tokens = {f["token"] for f in files if f.get("token")}

        # 查找已入库但飞书侧已不存在的文件
        registered = await FeishuFolderFile.filter(
            folder_watch_id=watch.id,
            ingest_status__in=["ingested", "pending"],
        )
        deleted_records = [r for r in registered if r.file_token not in feishu_tokens]

        if not deleted_records:
            return 0

        for record in deleted_records:
            record.ingest_status = "feishu_deleted"
            record.ingest_error = "飞书侧文件已删除，待人工清理"
            await record.save()

        logger.info(
            f"[FeishuFolderScan] detected feishu_deleted: watch_id={watch.id}, "
            f"count={len(deleted_records)}"
        )
        return len(deleted_records)

    async def cleanup_deleted_file(self, folder_watch_id: int, file_token: str) -> None:
        """人工清理飞书侧已删除的文件：联动删除 Document 及关联数据。"""
        record = await FeishuFolderFile.get(
            folder_watch_id=folder_watch_id, file_token=file_token
        )
        if record.ingest_status != "feishu_deleted":
            raise ValueError("只能清理飞书侧已删除状态的文件")

        if record.document_id:
            # 复用 documents.py 的清理逻辑
            doc = await Document.get_or_none(id=record.document_id)
            if doc and not doc.is_deleted:
                from app.services.chunk_service import chunk_service
                from app.models.rag import SlicingResult

                # 1. 清理向量
                await chunk_service.delete_by_doc_id(record.document_id)
                # 2. 清理切片
                await SlicingResult.filter(document_id=record.document_id).delete()
                # 3. 清理页面
                from app.models.rag import DocumentPage
                pages = await DocumentPage.filter(document_id=record.document_id)
                for page in pages:
                    if page.screenshot_url:
                        try:
                            from app.services.file_storage import file_storage
                            await file_storage.delete(page.screenshot_url)
                        except Exception:
                            pass
                await DocumentPage.filter(document_id=record.document_id).delete()
                # 4. 软删除文档
                doc.is_deleted = True
                await doc.save()
                logger.info(
                    f"[FeishuFolderScan] cleaned up document: doc_id={record.document_id}"
                )

        # 更新 FeishuFolderFile 状态为已清理
        record.ingest_status = "cleaned"
        record.ingest_error = None
        await record.save()
        logger.info(
            f"[FeishuFolderScan] file cleaned: watch_id={folder_watch_id}, token={file_token}"
        )

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
    
        # 1. 登记 pending（先占位，确保幂等锡立即生效）
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
    
        # 4. 打标记锁：告知补偿任务这个文档由飞书夹扫托管，不要背底尝试
        #    TTL 3600s 覆盖整个提取周期，_auto_process / process_document 完成后自动释放
        await self._set_ingest_lock(doc.id)
    
        # 5. 触发流水线：auto_approve 时跳过审核直接向量化
        if watch.auto_approve:
            asyncio.create_task(self._auto_process(doc.id))
        else:
            asyncio.create_task(self._process_and_release_lock(doc.id))
    
        logger.info(
            f"[FeishuFolderScan] ingested: watch_id={watch.id}, token={file_token}, "
            f"doc_id={doc.id}, type_code={watch.doc_type_code}, "
            f"auto_approve={watch.auto_approve}"
        )
        return True
    
    async def _set_ingest_lock(self, doc_id: int) -> None:
        """Set 标记锁，告知补偿任务该文档由飞书夹扫托管。"""
        redis = get_redis()
        lock_key = f"{LockKey.FEISHU_FOLDER_INGEST}:{doc_id}"
        # 不需要 token：这是“标记”而非“互斥锁”，标记存在即表示托管
        await redis.set(lock_key, "1", ex=3600)
        logger.debug(f"[FeishuFolderScan] ingest_lock set: doc_id={doc_id}")
    
    async def _release_ingest_lock(self, doc_id: int) -> None:
        """释放标记锁，提取完成后调用。"""
        redis = get_redis()
        lock_key = f"{LockKey.FEISHU_FOLDER_INGEST}:{doc_id}"
        await redis.delete(lock_key)
        logger.debug(f"[FeishuFolderScan] ingest_lock released: doc_id={doc_id}")
    
    async def _process_and_release_lock(self, doc_id: int) -> None:
        """非 auto_approve 路径：提取完成后释放托管锁。"""
        try:
            await document_pipeline.process_document(doc_id)
        finally:
            # 提取成功或失败均释放锁，让补偿任务可以接管 FAILED 状态的文档
            await self._release_ingest_lock(doc_id)

    async def _auto_process(self, doc_id: int) -> None:
        """auto_approve 路径：提取 → 自动跳过审核 → 向量化。"""
        try:
            await document_pipeline.process_document(doc_id)
            # process_document 完成后 doc 状态为 PENDING_REVIEW，直接触发向量化
            doc = await Document.get(id=doc_id)
            if doc.status == DocumentStatus.PENDING_REVIEW:
                doc.status = DocumentStatus.APPROVED
                await doc.save()
                await document_pipeline.vectorize_document(doc_id)
                logger.info(f"[FeishuFolderScan] auto_approved: doc_id={doc_id}")
        except Exception:
            logger.exception(f"[FeishuFolderScan] auto_process failed: doc_id={doc_id}")
        finally:
            # 无论成败均释放托管锁
            await self._release_ingest_lock(doc_id)

    async def _re_ingest_updated_files(
        self, watch: FeishuFolderWatch, updated_files: list[dict]
    ) -> int:
        """处理变更文件：清除旧向量 → 更新 FeishuFolderFile → 重新入库。"""
        if not updated_files:
            return 0

        batch_limit = settings.FEISHU_FOLDER_SCAN_BATCH_LIMIT
        batch = updated_files[:batch_limit]
        if len(updated_files) > batch_limit:
            logger.info(
                f"[FeishuFolderScan] update batch truncated: watch_id={watch.id}, "
                f"{len(updated_files)} → {batch_limit}"
            )

        re_ingested = 0
        for f in batch:
            try:
                if await self._re_ingest_one(watch, f):
                    re_ingested += 1
            except Exception as e:
                logger.exception(
                    f"[FeishuFolderScan] re-ingest failed: watch_id={watch.id}, "
                    f"token={f.get('token')}"
                )
        return re_ingested

    async def _re_ingest_one(self, watch: FeishuFolderWatch, file_meta: dict) -> bool:
        """单文件重新入库：先清除旧 Document 的向量，再走完整提取流程。"""
        file_token = file_meta["token"]
        record = await FeishuFolderFile.get(
            folder_watch_id=watch.id, file_token=file_token
        )

        if not record.document_id:
            logger.warning(
                f"[FeishuFolderScan] updated file has no document_id, skip: "
                f"watch_id={watch.id}, token={file_token}"
            )
            return False

        # 清除旧文档的向量数据
        try:
            from app.services.rag_service import rag_service
            await rag_service.delete_document(str(record.document_id))
            logger.info(
                f"[FeishuFolderScan] cleaned old vectors: doc_id={record.document_id}"
            )
        except Exception as e:
            logger.warning(
                f"[FeishuFolderScan] clean old vectors failed (non-fatal): "
                f"doc_id={record.document_id}, error={e}"
            )

        # 重置 Document 状态，触发重新提取
        doc = await Document.get(id=record.document_id)
        doc.status = DocumentStatus.PENDING_EXTRACT
        doc.content = None
        doc.error_message = None
        new_mtime = file_meta.get("modified_time")
        if new_mtime:
            doc.source_meta = {**(doc.source_meta or {}), "feishu_modified_time": int(new_mtime)}
        await doc.save()

        # 更新 FeishuFolderFile
        record.feishu_modified_time = int(new_mtime) if new_mtime else record.feishu_modified_time
        record.ingest_status = "ingested"
        record.ingest_error = None
        await record.save()

        # 重置托管锁：覆盖旧锁（如果有），確保补偿任务在重新提取期间不干扰
        await self._set_ingest_lock(doc.id)

        # 触发流水线
        if watch.auto_approve:
            asyncio.create_task(self._auto_process(doc.id))
        else:
            asyncio.create_task(self._process_and_release_lock(doc.id))

        logger.info(
            f"[FeishuFolderScan] re-ingested: watch_id={watch.id}, token={file_token}, "
            f"doc_id={doc.id}"
        )
        return True

    async def _get_access_token(self) -> str:
        """获取飞书 tenant_access_token，带进程内缓存（TTL 90 分钟）。"""
        app_id = settings.FEISHU_DOC_BOT_APPID
        now = time.time()
        cached = _token_cache.get(app_id)
        if cached and cached[1] > now:
            return cached[0]

        token = await feishu_service.get_tenant_access_token(
            app_id, settings.FEISHU_DOC_BOT_APPSECRET
        )
        _token_cache[app_id] = (token, now + _TOKEN_TTL)
        logger.debug(f"[FeishuFolderScan] access_token refreshed for app_id={app_id[:8]}...")
        return token

    async def _collect_all_files(
        self, watch: FeishuFolderWatch, access_token: str, max_files: int = 5000,
    ) -> list[dict]:
        """收集文件列表，支持递归子文件夹。"""
        if not watch.recursive_scan:
            return await feishu_service.list_files_in_folder(
                folder_token=watch.folder_token,
                access_token=access_token,
                max_files=max_files,
            )

        # 递归模式：BFS 遍历子文件夹
        all_files: list[dict] = []
        folder_queue = [watch.folder_token]
        visited_folders: set[str] = set()

        while folder_queue and len(all_files) < max_files:
            current_folder = folder_queue.pop(0)
            if current_folder in visited_folders:
                continue
            visited_folders.add(current_folder)

            files = await feishu_service.list_files_in_folder(
                folder_token=current_folder,
                access_token=access_token,
                max_files=max_files - len(all_files),
            )
            for f in files:
                if f.get("type") == "folder" and f.get("token"):
                    folder_queue.append(f["token"])
                elif f.get("type") not in _SKIP_TYPES and f.get("token"):
                    all_files.append(f)

            if len(all_files) >= max_files:
                logger.warning(
                    f"[FeishuFolderScan] recursive scan hit max_files={max_files}: "
                    f"watch_id={watch.id}"
                )
                break

        return all_files

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
