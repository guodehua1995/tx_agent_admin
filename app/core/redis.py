"""Redis 异步客户端初始化"""

import redis.asyncio as aioredis

from app.settings.config import settings

# 全局 Redis 客户端实例
_redis_client: aioredis.Redis | None = None


async def init_redis() -> aioredis.Redis:
    """初始化 Redis 连接池"""
    global _redis_client
    _redis_client = aioredis.from_url(
        settings.REDIS_URL,
        decode_responses=True,
        max_connections=50,
    )
    # 验证连接
    await _redis_client.ping()
    from app.log import logger
    logger.info(f"[Redis] Connected: {settings.REDIS_URL}")
    return _redis_client


async def close_redis():
    """关闭 Redis 连接"""
    global _redis_client
    if _redis_client:
        await _redis_client.aclose()
        _redis_client = None


def get_redis() -> aioredis.Redis:
    """获取 Redis 客户端实例"""
    if _redis_client is None:
        raise RuntimeError("Redis client not initialized. Call init_redis() first.")
    return _redis_client
