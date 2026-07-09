"""LangGraph PostgreSQL checkpointer 共享模块

为 deepagents 提供基于 PostgreSQL 的 agent 状态持久化能力。
每次 agent.ainvoke() 时自动将消息、工具调用、工具结果写入 checkpoint 表，
下次同一 thread_id 调用时自动恢复上下文。
"""

from __future__ import annotations

from langgraph.checkpoint.postgres.aio import AsyncPostgresSaver
from psycopg import AsyncConnection

from app.log import logger

_checkpointer: AsyncPostgresSaver | None = None
_conn: AsyncConnection | None = None


async def init_checkpointer(db_url: str) -> AsyncPostgresSaver:
    """初始化 checkpointer 并创建 checkpoint 表（幂等）

    应在 app 启动时调用一次，连接保持到进程退出。
    """
    global _checkpointer, _conn

    logger.info(f"[Checkpointer] Connecting to PostgreSQL...")
    _conn = await AsyncConnection.connect(
        db_url, autocommit=True, prepare_threshold=0,
    )
    _checkpointer = AsyncPostgresSaver(conn=_conn)
    await _checkpointer.setup()
    logger.info(f"[Checkpointer] Initialized successfully")
    return _checkpointer


async def close_checkpointer() -> None:
    """关闭 checkpointer 连接"""
    global _checkpointer, _conn
    if _conn is not None:
        await _conn.close()
        _conn = None
        _checkpointer = None
        logger.info(f"[Checkpointer] Connection closed")


def get_checkpointer() -> AsyncPostgresSaver:
    """获取全局 checkpointer 实例"""
    if _checkpointer is None:
        raise RuntimeError("Checkpointer not initialized. Call init_checkpointer() first.")
    return _checkpointer