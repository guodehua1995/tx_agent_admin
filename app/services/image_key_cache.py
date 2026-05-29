"""飞书 IM 图片 image_key 缓存

设计目标：同一份页截图（screenshot_key）在同一 bot（app_id）下
只调一次 /im/v1/images，复用拿到的 image_key。

- Key:   (app_id, screenshot_key) → image_key
- 后端:  memory | redis（redis 接入预留扩展点）
- 失效:  支持 TTL（默认 7 天，0 表示不过期）+ 容量上限淘汰

注意：飞书 image_key 与 app 维度强绑定，跨 bot 不可复用，
因此缓存键 MUST 带 app_id 维度，否则会出现"X bot 的 key 给 Y bot 用"的引用失败。
"""

from __future__ import annotations

import asyncio
import time
from abc import ABC, abstractmethod
from collections import OrderedDict
from typing import Optional

from app.log import logger
from app.settings import settings


class ImageKeyCache(ABC):
    """image_key 缓存抽象"""

    @abstractmethod
    async def get(self, app_id: str, screenshot_key: str) -> Optional[str]:
        """命中返回 image_key，未命中返回 None"""
        ...

    @abstractmethod
    async def set(self, app_id: str, screenshot_key: str, image_key: str) -> None:
        """写入缓存"""
        ...


# ============================================================
# 本地内存实现：LRU + TTL
# ============================================================


class MemoryImageKeyCache(ImageKeyCache):
    """单进程内存缓存：OrderedDict 实现 LRU，过期/超容量自动淘汰"""

    def __init__(self, max_size: int = 1024, ttl: int = 7 * 24 * 3600):
        self._max_size = max(1, int(max_size))
        self._ttl = max(0, int(ttl))
        self._data: "OrderedDict[str, tuple[str, float]]" = OrderedDict()
        self._lock = asyncio.Lock()

    @staticmethod
    def _key(app_id: str, screenshot_key: str) -> str:
        return f"{app_id}::{screenshot_key}"

    async def get(self, app_id: str, screenshot_key: str) -> Optional[str]:
        if not app_id or not screenshot_key:
            return None
        k = self._key(app_id, screenshot_key)
        async with self._lock:
            entry = self._data.get(k)
            if not entry:
                return None
            value, expire_at = entry
            if expire_at and expire_at < time.time():
                self._data.pop(k, None)
                return None
            self._data.move_to_end(k)
            return value

    async def set(self, app_id: str, screenshot_key: str, image_key: str) -> None:
        if not app_id or not screenshot_key or not image_key:
            return
        k = self._key(app_id, screenshot_key)
        expire_at = time.time() + self._ttl if self._ttl > 0 else 0.0
        async with self._lock:
            self._data[k] = (image_key, expire_at)
            self._data.move_to_end(k)
            while len(self._data) > self._max_size:
                self._data.popitem(last=False)


# ============================================================
# Redis 实现占位（后续按需接入）
# ============================================================


class RedisImageKeyCache(ImageKeyCache):  # pragma: no cover - 预留扩展
    """Redis 后端占位实现，待集成 redis.asyncio 客户端后启用"""

    def __init__(self, *args, **kwargs):
        raise NotImplementedError(
            "RedisImageKeyCache 尚未实现，请暂时使用 IMAGE_KEY_CACHE_BACKEND=memory"
        )

    async def get(self, app_id: str, screenshot_key: str) -> Optional[str]:
        raise NotImplementedError

    async def set(self, app_id: str, screenshot_key: str, image_key: str) -> None:
        raise NotImplementedError


# ============================================================
# 工厂
# ============================================================


def _create_cache() -> ImageKeyCache:
    backend = (getattr(settings, "IMAGE_KEY_CACHE_BACKEND", "memory") or "memory").lower()
    max_size = getattr(settings, "IMAGE_KEY_CACHE_MAX_SIZE", 1024)
    ttl = getattr(settings, "IMAGE_KEY_CACHE_TTL", 7 * 24 * 3600)

    if backend == "memory":
        return MemoryImageKeyCache(max_size=max_size, ttl=ttl)
    if backend == "redis":
        logger.warning(
            f"[ImageKeyCache] redis 后端尚未实现，回退到内存缓存"
            f"（max_size={max_size}, ttl={ttl}）"
        )
        return MemoryImageKeyCache(max_size=max_size, ttl=ttl)
    raise ValueError(f"不支持的 image_key 缓存后端: {backend}")


image_key_cache: ImageKeyCache = _create_cache()
