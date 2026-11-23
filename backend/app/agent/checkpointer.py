"""M4 记忆持久化 —— LangGraph checkpointer 管理。

用 SqliteSaver 把每个会话（thread）的状态存到本地 SQLite 文件里。
不同 thread_id 的会话互相隔离，实现"多会话并行"。

数据库文件默认在 backend/data/checkpoints.db。
"""

from __future__ import annotations

import os
from contextlib import asynccontextmanager
from typing import AsyncIterator

import aiosqlite
from langgraph.checkpoint.sqlite.aio import AsyncSqliteSaver

from app.config import get_settings

#: 已创建的 saver 实例缓存，避免重复打开数据库连接
_saver: AsyncSqliteSaver | None = None


def _db_path() -> str:
    """返回 SQLite 数据库文件路径，确保所在目录存在。"""
    path = get_settings().checkpoint_db_path
    directory = os.path.dirname(path)
    if directory:
        os.makedirs(directory, exist_ok=True)
    return path


async def get_checkpointer() -> AsyncSqliteSaver:
    """获取（并在首次调用时创建）全局 checkpointer。

    注意 AsyncSqliteSaver.from_conn_string 是个 async context manager，
    用完连接就断了。所以这里自己用 aiosqlite 建连接再包一层，
    让连接在整个应用生命周期内保持打开。
    """
    global _saver
    if _saver is None:
        conn = await aiosqlite.connect(_db_path())
        saver = AsyncSqliteSaver(conn)
        # 建表（首次会执行建表 SQL，之后是空操作）
        await saver.setup()
        _saver = saver
    return _saver


@asynccontextmanager
async def checkpointer_scope() -> AsyncIterator[AsyncSqliteSaver]:
    """应用启动时打开 checkpointer，关闭时释放。

    用法（main.py 的 lifespan）：
        async with checkpointer_scope() as saver:
            yield
    """
    saver = await get_checkpointer()
    try:
        yield saver
    finally:
        global _saver
        if _saver is not None:
            await _saver.conn.close()
            _saver = None
