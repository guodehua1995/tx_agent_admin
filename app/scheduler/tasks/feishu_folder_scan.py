"""飞书云盘文件夹扫描定时任务

扫描所有启用的 FeishuFolderWatch，发现新增文件 → 自动入库。
单 watch 内部已加 Redis 锁保证多实例互斥。
"""

from app.log import logger
from app.services.feishu_folder_scan import feishu_folder_scan_service
from app.settings import settings


async def scan_feishu_folders():
    """扫描所有启用的飞书文件夹监听。"""
    if not settings.FEISHU_FOLDER_SCAN_ENABLED:
        return
    try:
        await feishu_folder_scan_service.scan_all()
    except Exception:
        logger.exception("[FeishuFolderScan] scan_all failed")
