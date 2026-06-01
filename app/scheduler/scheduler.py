"""定时调度器核心：基于 asyncio 的周期扫描循环"""

import asyncio

from app.log import logger
from app.settings.config import settings

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
        """依次执行所有注册的补偿任务"""
        tasks = get_all_tasks()
        for task_func in tasks:
            if not self._running:
                break
            try:
                await task_func()
            except Exception:
                logger.exception(f"[Scheduler] Task {task_func.__name__} failed")
