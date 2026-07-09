"""定时调度器核心：基于 asyncio 的周期扫描循环"""

import asyncio

from app.core.redis_lock import LockKey, RedisLock
from app.log import logger
from app.settings.config import settings

from .scheduler_lock import SCHEDULER_LOCK_TTL, reset_scheduler_lock, renew_scheduler_lock, set_scheduler_lock
from .tasks import get_all_tasks


class TaskScheduler:
    """定时任务补偿调度器

    在应用 lifespan 中启动，按 SCHEDULER_INTERVAL 周期扫描并执行补偿任务。
    通过 Redis 分布式锁保证多实例间不重复执行。
    """

    def __init__(self):
        self._task: asyncio.Task | None = None
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
        self._task = asyncio.create_task(self._scan_loop())
        logger.info(
            f"[Scheduler] Started: interval={settings.SCHEDULER_INTERVAL}s, "
            f"env={settings.ENV}"
        )

    async def stop(self):
        """优雅停止调度器"""
        self._running = False
        if self._task and not self._task.done():
            self._task.cancel()
            try:
                await self._task
            except asyncio.CancelledError:
                pass
            self._task = None
        logger.info("[Scheduler] Stopped")

    async def _scan_loop(self):
        """主扫描循环"""
        while self._running:
            try:
                await asyncio.sleep(settings.SCHEDULER_INTERVAL)
                if not self._running:
                    break
                await self._run_all_tasks()
            except asyncio.CancelledError:
                break
            except Exception:
                logger.exception("[Scheduler] Scan loop error, will retry next cycle")

    async def _run_all_tasks(self):
        """依次执行所有注册的补偿任务

        通过 Redis 分布式锁确保多 worker 下只有一个 worker 执行本轮任务。
        每个任务执行前续活锁，防止长时间任务导致锁过期。
        """
        lock = RedisLock()
        token = await lock.acquire(LockKey.SCHEDULER_SCAN, ttl=SCHEDULER_LOCK_TTL)
        if not token:
            logger.debug("[Scheduler] Another worker is running tasks, skip this cycle")
            return

        # 将锁信息存入上下文变量，供子任务续活
        ctx_token = set_scheduler_lock(LockKey.SCHEDULER_SCAN, token, lock)

        try:
            tasks = get_all_tasks()
            for task_func in tasks:
                if not self._running:
                    break
                # 每个任务执行前续活锁
                await renew_scheduler_lock()
                try:
                    await task_func()
                except Exception:
                    logger.exception(f"[Scheduler] Task {task_func.__name__} failed")
        finally:
            reset_scheduler_lock(ctx_token)
            await lock.release(LockKey.SCHEDULER_SCAN, token)
