"""调度器锁上下文：供长循环任务续活调度器分布式锁

通过 contextvars 在调度器执行期间存储锁信息，
子任务（如 compensate_pending_extract）可调用 renew_scheduler_lock() 续活，
防止长循环执行时间超过锁 TTL 导致被其他 worker 抢占。
"""

import contextvars
from typing import Any

from app.core.redis_lock import RedisLock
from app.log import logger

# 调度器锁 TTL（与 scheduler.py 保持一致）
SCHEDULER_LOCK_TTL = 600

# 上下文变量：存储当前调度器的锁信息
# 值为 dict: {"key": str, "token": str, "lock": RedisLock}
_scheduler_lock_ctx: contextvars.ContextVar[dict[str, Any] | None] = contextvars.ContextVar(
    "scheduler_lock", default=None
)


def set_scheduler_lock(key: str, token: str, lock: RedisLock) -> contextvars.Token:
    """将调度器锁信息存入上下文变量，返回 reset token。"""
    return _scheduler_lock_ctx.set({"key": key, "token": token, "lock": lock})


def reset_scheduler_lock(token: contextvars.Token) -> None:
    """重置调度器锁上下文。"""
    _scheduler_lock_ctx.reset(token)


async def renew_scheduler_lock() -> None:
    """续活调度器分布式锁。

    供长循环任务（如 compensate_pending_extract）在每次迭代时调用，
    防止整个任务执行时间超过锁 TTL 导致被其他 worker 抢占。
    非调度器上下文调用时静默跳过（如手动触发任务）。
    """
    info = _scheduler_lock_ctx.get()
    if info is None:
        return  # 非调度器上下文，无需续活
    renewed = await info["lock"].renew(info["key"], info["token"], ttl=SCHEDULER_LOCK_TTL)
    if not renewed:
        logger.warning("[Scheduler] Lock renewal failed in task, another worker may have taken over")
