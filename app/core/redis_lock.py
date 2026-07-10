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
    SCHEDULER_APPROVED = "tx_agent:lock:scheduler_approved"  # approved 补偿任务独立锁
    FEISHU_FOLDER_SCAN = "tx_agent:lock:feishu_folder_scan"
    # 标记该 Document 由飞书文件夹监听托管，补偿任务跳过
    FEISHU_FOLDER_INGEST = "tx_agent:lock:feishu_folder_ingest"
    # OCR 全局互斥锁：跨 worker 确保同时只有一个 OCR 请求
    OCR_GLOBAL = "tx_agent:lock:ocr_global"
    # 向量化全局互斥锁：跨 worker 确保同时只有一个向量化任务
    VECTORIZE_GLOBAL = "tx_agent:lock:vectorize_global"


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

    async def renew(self, key: str, token: str, ttl: int = 300) -> bool:
        """续活锁（延长 TTL），仅当 token 匹配时生效

        Returns:
            True 续活成功，False token 不匹配或锁已过期
        """
        redis = get_redis()
        # Lua: 验证 token 后重置 TTL
        lua = """
if redis.call("get", KEYS[1]) == ARGV[1] then
    return redis.call("expire", KEYS[1], ARGV[2])
else
    return 0
end
"""
        result = await redis.eval(lua, 1, key, token, ttl)
        return bool(result)

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
