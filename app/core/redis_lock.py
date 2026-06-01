"""Redis 分布式锁 + 锁 key 常量管理"""

import secrets
from enum import StrEnum

from app.core.redis import get_redis
from app.log import logger

# ── Lua 脚本：原子释放（验证 token 后 DEL） ──────────────────────
_RELEASE_SCRIPT = """
if redis.call("get", KEYS[1]) == ARGV[1] then
    return redis.call("del", KEYS[1])
else
    return 0
end
"""


# ── 锁 key 常量 ──────────────────────────────────────────────────
class LockKey(StrEnum):
    """Redis 分布式锁 key 前缀常量

    使用方式: f"{LockKey.DOCUMENT_PROCESS}:{doc_id}"
    """

    DOCUMENT_PROCESS = "tx_agent:lock:doc_process"
    DOCUMENT_VECTORIZE = "tx_agent:lock:doc_vectorize"
    SCHEDULER_SCAN = "tx_agent:lock:scheduler_scan"


# ── 锁操作 ──────────────────────────────────────────────────────
class RedisLock:
    """Redis 分布式锁

    用法::

        lock = RedisLock()
        token = await lock.acquire(f"{LockKey.DOCUMENT_PROCESS}:42", ttl=300)
        if token:
            try:
                ...  # 执行业务
            finally:
                await lock.release(f"{LockKey.DOCUMENT_PROCESS}:42", token)
    """

    async def acquire(self, key: str, ttl: int = 300) -> str | None:
        """尝试获取锁

        Args:
            key: 锁 key（建议使用 LockKey 常量拼接资源 ID）
            ttl: 锁过期时间（秒），防止死锁

        Returns:
            token 字符串（获取成功）或 None（获取失败）
        """
        redis = get_redis()
        token = secrets.token_hex(16)
        ok = await redis.set(key, token, nx=True, ex=ttl)
        if ok:
            logger.debug(f"[RedisLock] Acquired: key={key}")
            return token
        logger.debug(f"[RedisLock] Failed to acquire: key={key}")
        return None

    async def release(self, key: str, token: str) -> bool:
        """释放锁（Lua 脚本原子操作，验证 token 归属）

        Returns:
            True 释放成功，False 锁已过期或 token 不匹配
        """
        redis = get_redis()
        result = await redis.eval(_RELEASE_SCRIPT, 1, key, token)
        released = bool(result)
        if released:
            logger.debug(f"[RedisLock] Released: key={key}")
        else:
            logger.debug(f"[RedisLock] Release skipped (expired/mismatch): key={key}")
        return released
