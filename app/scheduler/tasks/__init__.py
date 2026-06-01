"""定时补偿任务注册"""

from typing import Awaitable, Callable

from .doc_compensate import (
    compensate_approved,
    compensate_pending_extract,
    reset_stuck_documents,
)

# 所有补偿任务列表（按执行顺序）
_ALL_TASKS: list[Callable[[], Awaitable[None]]] = [
    reset_stuck_documents,       # 先重置卡住的任务
    compensate_pending_extract,  # 再补偿待提取的
    compensate_approved,         # 最后补偿已通过审核的
]


def get_all_tasks() -> list[Callable[[], Awaitable[None]]]:
    """返回所有注册的补偿任务"""
    return _ALL_TASKS
