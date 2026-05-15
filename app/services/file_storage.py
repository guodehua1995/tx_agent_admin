"""
文件存储服务 — 策略模式

提供统一的文件存储抽象接口，当前实现为本地文件系统存储，
后续可替换为 OSS / S3 等云存储实现，只需新增 Backend 子类即可。
"""

from abc import ABC, abstractmethod
from pathlib import Path

from app.log import logger
from app.settings import settings


class FileStorageBackend(ABC):
    """文件存储抽象接口"""

    @abstractmethod
    async def save(self, path: str, data: bytes) -> str:
        """保存文件，返回可访问 URL"""
        ...

    @abstractmethod
    async def delete(self, path: str) -> None:
        """删除文件"""
        ...

    @abstractmethod
    def get_url(self, path: str) -> str:
        """获取文件的可访问 URL"""
        ...


class LocalFileStorage(FileStorageBackend):
    """本地文件系统存储 — 文件存储于 MEDIA_ROOT 目录，通过 StaticFiles 提供 HTTP 访问"""

    def __init__(self, media_root: str, url_prefix: str):
        self.media_root = Path(media_root)
        self.url_prefix = url_prefix.rstrip("/")

    async def save(self, path: str, data: bytes) -> str:
        full_path = self.media_root / path
        full_path.parent.mkdir(parents=True, exist_ok=True)
        full_path.write_bytes(data)
        logger.debug(f"[FileStorage] Saved: {full_path} ({len(data)} bytes)")
        return self.get_url(path)

    async def delete(self, path: str) -> None:
        full_path = self.media_root / path
        if full_path.exists():
            full_path.unlink()
            logger.debug(f"[FileStorage] Deleted: {full_path}")

    def get_url(self, path: str) -> str:
        return f"{self.url_prefix}/{path}"


def _create_storage() -> FileStorageBackend:
    """根据配置创建存储后端实例"""
    backend = settings.FILE_STORAGE_BACKEND
    if backend == "local":
        return LocalFileStorage(
            media_root=settings.MEDIA_ROOT,
            url_prefix=settings.MEDIA_URL_PREFIX,
        )
    raise ValueError(f"不支持的文件存储后端: {backend}")


file_storage: FileStorageBackend = _create_storage()
