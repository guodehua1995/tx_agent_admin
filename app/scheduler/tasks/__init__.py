"""定时补偿任务注册"""

from typing import Awaitable, Callable

from .doc_compensate import (
    compensate_approved,
    compensate_pending_extract,
    reset_stuck_documents,
)
from .feishu_folder_scan import scan_feishu_folders
from .contract_expiry import check_contract_expiry
from .clause_summary import process_clause_summaries
from .contract_review import review_contracts
from .contract_cleanup import cleanup_temporary_contracts

# 所有补偿任务列表（按执行顺序）
_ALL_TASKS: list[Callable[[], Awaitable[None]]] = [
    reset_stuck_documents,       # 先重置卡住的任务
    compensate_pending_extract,  # 再补偿待提取的
    compensate_approved,         # 最后补偿已通过审核的
    scan_feishu_folders,         # 扫描飞书云盘文件夹（新增文件自动入库）
    check_contract_expiry,       # 合同到期提醒
    process_clause_summaries,    # 合同条款摘要异步处理
    review_contracts,            # 合同风险审查
    cleanup_temporary_contracts,  # 临时合同清理
]


def get_all_tasks() -> list[Callable[[], Awaitable[None]]]:
    """返回所有注册的补偿任务"""
    return _ALL_TASKS
