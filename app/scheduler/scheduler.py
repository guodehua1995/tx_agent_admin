"""定时调度器核心：基于 asyncio 的周期扫描循环"""

import asyncio

from app.core.redis_lock import LockKey, RedisLock
from app.core.scheduler_lock import SCHEDULER_LOCK_TTL, reset_scheduler_lock, renew_scheduler_lock, set_scheduler_lock
from app.log import logger
from app.settings.config import settings

from .tasks import get_all_tasks
from .tasks.doc_compensate import compensate_approved


class TaskScheduler:
    """定时任务补偿调度器

    在应用 lifespan 中启动，按 SCHEDULER_INTERVAL 周期扫描并执行补偿任务。
    通过 Redis 分布式锁保证多实例间不重复执行。

    两个独立循环：
    - 主循环：执行 reset_stuck / compensate_pending_extract / scan_feishu 等任务
    - approved 循环：独立运行 compensate_approved，不受主循环阻塞
    """

    def __init__(self):
        self._tasks: list[asyncio.Task] = []
        self._running = False

    async def start(self):
        """启动调度器"""
        # 环境过滤
        if not settings.SCHEDULER_ENABLED:
            logger.info("[Scheduler] Disabled by SCHEDULER_ENABLED=False")
            return

        if settings.SCHEDULER_DEV_ONLY and settings.ENV != "development":
            logger.info(f"[Scheduler] Skipped: SCHEDULER_DEV_ONLY=True but ENV={settings.ENV}")
            return

        self._running = True
        # 主循环：reset_stuck / compensate_pending_extract / feishu 等
        self._tasks.append(asyncio.create_task(self._scan_loop()))
        # approved 独立循环：不与主循环共享锁，不被阻塞
        self._tasks.append(asyncio.create_task(self._approved_loop()))
        logger.info(
            f"[Scheduler] Started: interval={settings.SCHEDULER_INTERVAL}s, "
            f"env={settings.ENV}"
        )

    async def stop(self):
        """优雅停止调度器"""
        self._running = False
        for t in self._tasks:
            t.cancel()
        for t in self._tasks:
            try:
                await t
            except asyncio.CancelledError:
                pass
        self._tasks.clear()
        logger.info("[Scheduler] Stopped")

    async def _scan_loop(self):
        """主扫描循环：执行除 compensate_approved 之外的所有任务"""
        while self._running:
            try:
                await asyncio.sleep(settings.SCHEDULER_INTERVAL)
                if not self._running:
                    break
                await self._run_main_tasks()
            except asyncio.CancelledError:
                break
            except Exception:
                logger.exception("[Scheduler] Main scan loop error, will retry next cycle")

    async def _approved_loop(self):
        """approved 补偿任务独立循环：不受主循环阻塞"""
        while self._running:
            try:
                await asyncio.sleep(settings.SCHEDULER_INTERVAL)
                if not self._running:
                    break
                await self._run_compensate_approved()
            except asyncio.CancelledError:
                break
            except Exception:
                logger.exception("[Scheduler] Approved loop error, will retry next cycle")

    async def _run_main_tasks(self):
        """执行主任务列表（compensate_approved 已拆出独立循环）"""
        lock = RedisLock()
        token = await lock.acquire(LockKey.SCHEDULER_SCAN, ttl=SCHEDULER_LOCK_TTL)
        if not token:
            logger.debug("[Scheduler] Another worker is running main tasks, skip this cycle")
            return

        ctx_token = set_scheduler_lock(LockKey.SCHEDULER_SCAN, token, lock)
        try:
            tasks = get_all_tasks()
            for task_func in tasks:
                if not self._running:
                    break
                await renew_scheduler_lock()
                try:
                    await task_func()
                except Exception:
                    logger.exception(f"[Scheduler] Task {task_func.__name__} failed")
        finally:
            reset_scheduler_lock(ctx_token)
            await lock.release(LockKey.SCHEDULER_SCAN, token)

    async def _run_compensate_approved(self):
        """独立执行 compensate_approved，使用单独的锁"""
        lock = RedisLock()
        token = await lock.acquire(LockKey.SCHEDULER_APPROVED, ttl=SCHEDULER_LOCK_TTL)
        if not token:
            return  # 另一个 worker 正在处理 approved，跳过

        ctx_token = set_scheduler_lock(LockKey.SCHEDULER_APPROVED, token, lock)
        try:
            await compensate_approved()
        except Exception:
            logger.exception("[Scheduler] compensate_approved failed")
        finally:
            reset_scheduler_lock(ctx_token)
            await lock.release(LockKey.SCHEDULER_APPROVED, token)
