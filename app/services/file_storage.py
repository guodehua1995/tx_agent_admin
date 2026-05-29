"""
文件存储服务 — 策略模式

提供统一的文件存储抽象接口，当前支持本地文件系统与火山引擎 TOS 对象存储，
新增后端只需新增 Backend 子类即可。

约定：
- save() 返回该资源的"对象 key / 相对路径"，DB 持久化此值；
- presign() 输出可供前端/外部访问的临时 URL；
- 本地后端的 presign 直接拼静态访问路径，与 expires 无关；
- TOS 后端的 presign 调用 SDK 生成预签名 URL，单次最大 7 天（604800s）。
"""

import asyncio
from abc import ABC, abstractmethod
from pathlib import Path
from typing import Optional

from app.log import logger
from app.settings import settings


# TOS 预签名 URL 单次最大有效期（火山官方上限 = 7 天）
TOS_PRESIGN_MAX_EXPIRES = 7 * 24 * 3600


class FileStorageBackend(ABC):
    """文件存储抽象接口"""

    @abstractmethod
    async def save(self, path: str, data: bytes) -> str:
        """保存文件，返回该资源的对象 key（即入参 path），由调用方持久化"""
        ...

    @abstractmethod
    async def delete(self, path: str) -> None:
        """删除单个文件，不存在不抛错"""
        ...

    @abstractmethod
    async def delete_prefix(self, prefix: str) -> int:
        """删除指定前缀下所有对象，返回删除数量；用于文档级目录清理"""
        ...

    @abstractmethod
    async def exists(self, path: str) -> bool:
        """判断文件是否存在"""
        ...

    @abstractmethod
    async def read_bytes(self, path: str) -> bytes:
        """读取文件字节，主要用于飞书侧需要二次上传图片"""
        ...

    @abstractmethod
    async def presign(self, path: str, expires: int = 3600) -> str:
        """生成预签名 URL（本地后端忽略 expires，返回静态 URL）"""
        ...

    def get_url(self, path: str) -> str:
        """获取默认访问 URL（同步、不签名），保留兼容老代码"""
        return path


# ============================================================
# 本地文件存储
# ============================================================


class LocalFileStorage(FileStorageBackend):
    """本地文件系统存储 — 文件落于 MEDIA_ROOT，通过 StaticFiles 暴露 HTTP 访问"""

    def __init__(self, media_root: str, url_prefix: str):
        self.media_root = Path(media_root)
        self.url_prefix = url_prefix.rstrip("/")

    def _full(self, path: str) -> Path:
        return self.media_root / path

    async def save(self, path: str, data: bytes) -> str:
        full_path = self._full(path)
        full_path.parent.mkdir(parents=True, exist_ok=True)
        full_path.write_bytes(data)
        logger.debug(f"[LocalFileStorage] Saved: {full_path} ({len(data)} bytes)")
        return path

    async def delete(self, path: str) -> None:
        full_path = self._full(path)
        if full_path.exists():
            full_path.unlink()
            logger.debug(f"[LocalFileStorage] Deleted: {full_path}")

    async def delete_prefix(self, prefix: str) -> int:
        import shutil

        target = self._full(prefix)
        if not target.exists() or not target.is_dir():
            return 0
        # 统计文件数后整体移除目录
        count = sum(1 for _ in target.rglob("*") if _.is_file())
        shutil.rmtree(target, ignore_errors=True)
        logger.debug(f"[LocalFileStorage] Deleted prefix: {target} (files={count})")
        return count

    async def exists(self, path: str) -> bool:
        return self._full(path).exists()

    async def read_bytes(self, path: str) -> bytes:
        return self._full(path).read_bytes()

    async def presign(self, path: str, expires: int = 3600) -> str:
        # 本地后端无签名概念，直接返回静态 URL
        return f"{self.url_prefix}/{path}"

    def get_url(self, path: str) -> str:
        return f"{self.url_prefix}/{path}"


# ============================================================
# 火山引擎 TOS 存储
# ============================================================


class TOSFileStorage(FileStorageBackend):
    """火山引擎 TOS 对象存储后端

    - SDK 调用为同步阻塞，统一使用 asyncio.to_thread 包装
    - save 返回 path 本身作为对象 key
    - 预签名 URL 单次最长 7 天，超过会被 SDK 拒绝；超过上限时强制截断为 7 天
    """

    def __init__(
        self,
        endpoint: str,
        region: str,
        access_key: str,
        secret_key: str,
        bucket: str,
    ):
        try:
            import tos
        except ImportError as e:  # pragma: no cover
            raise ImportError("缺少依赖 tos，请执行：uv pip install tos") from e

        if not all([endpoint, region, access_key, secret_key, bucket]):
            raise ValueError(
                "TOS 配置不完整，请检查 TOS_ENDPOINT/TOS_REGION/"
                "TOS_ACCESS_KEY/TOS_SECRET_KEY/TOS_BUCKET"
            )

        self._tos = tos
        self._client = tos.TosClientV2(access_key, secret_key, endpoint, region)
        self._bucket = bucket
        self._endpoint = endpoint
        logger.info(f"[TOSFileStorage] Initialized: bucket={bucket}, region={region}")

    # ── SDK 调用包装 ──

    async def _run(self, func, *args, **kwargs):
        return await asyncio.to_thread(func, *args, **kwargs)

    # ── 接口实现 ──

    async def save(self, path: str, data: bytes) -> str:
        from io import BytesIO

        await self._run(
            self._client.put_object,
            self._bucket,
            path,
            content=BytesIO(data),
        )
        logger.debug(f"[TOSFileStorage] Put: {path} ({len(data)} bytes)")
        return path

    async def delete(self, path: str) -> None:
        try:
            await self._run(self._client.delete_object, self._bucket, path)
            logger.debug(f"[TOSFileStorage] Deleted: {path}")
        except self._tos.exceptions.TosServerError as e:
            # 不存在视为删除成功
            if getattr(e, "status_code", None) == 404:
                return
            logger.warning(f"[TOSFileStorage] Delete failed: key={path}, err={e}")
            raise

    async def delete_prefix(self, prefix: str) -> int:
        """列对象 + 批量删除；TOS 单批最多 1000 个"""
        deleted = 0
        continuation_token: Optional[str] = None
        while True:
            kwargs = {"prefix": prefix, "max_keys": 1000}
            if continuation_token:
                kwargs["continuation_token"] = continuation_token
            resp = await self._run(
                self._client.list_objects_type2, self._bucket, **kwargs
            )
            keys = [obj.key for obj in (resp.contents or [])]
            if keys:
                ObjectTobeDeleted = self._tos.models2.ObjectTobeDeleted
                objects = [ObjectTobeDeleted(k) for k in keys]
                await self._run(
                    self._client.delete_multi_objects,
                    self._bucket,
                    objects,
                    quiet=True,
                )
                deleted += len(keys)
            if not resp.is_truncated:
                break
            continuation_token = resp.next_continuation_token
        if deleted:
            logger.debug(f"[TOSFileStorage] Deleted prefix: {prefix} (count={deleted})")
        return deleted

    async def exists(self, path: str) -> bool:
        try:
            await self._run(self._client.head_object, self._bucket, path)
            return True
        except self._tos.exceptions.TosServerError as e:
            if getattr(e, "status_code", None) == 404:
                return False
            raise

    async def read_bytes(self, path: str) -> bytes:
        resp = await self._run(self._client.get_object, self._bucket, path)
        # SDK 返回流对象，read() 是同步调用
        return await asyncio.to_thread(resp.read)

    async def presign(self, path: str, expires: int = 3600) -> str:
        if expires <= 0:
            expires = 3600
        if expires > TOS_PRESIGN_MAX_EXPIRES:
            logger.warning(
                f"[TOSFileStorage] presign expires={expires}s 超过上限 "
                f"{TOS_PRESIGN_MAX_EXPIRES}s，已截断"
            )
            expires = TOS_PRESIGN_MAX_EXPIRES
        resp = await self._run(
            self._client.pre_signed_url,
            self._tos.HttpMethodType.Http_Method_Get,
            self._bucket,
            path,
            expires,
        )
        return resp.signed_url

    def get_url(self, path: str) -> str:
        # 兼容老调用方：返回未签名的虚拟 URL（不可直接访问私有桶）
        return f"https://{self._bucket}.{self._endpoint}/{path}"


# ============================================================
# 工厂
# ============================================================


def _create_storage() -> FileStorageBackend:
    backend = (settings.FILE_STORAGE_BACKEND or "local").lower()
    if backend == "local":
        return LocalFileStorage(
            media_root=settings.MEDIA_ROOT,
            url_prefix=settings.MEDIA_URL_PREFIX,
        )
    if backend == "tos":
        return TOSFileStorage(
            endpoint=settings.TOS_ENDPOINT,
            region=settings.TOS_REGION,
            access_key=settings.TOS_ACCESS_KEY,
            secret_key=settings.TOS_SECRET_KEY,
            bucket=settings.TOS_BUCKET,
        )
    raise ValueError(f"不支持的文件存储后端: {backend}")


file_storage: FileStorageBackend = _create_storage()

