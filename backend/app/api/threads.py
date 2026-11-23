"""M4 会话列表接口 —— 列出所有 thread 及其最后活跃时间。

对应 PLAN.md §6.2：
  GET /api/threads   返回所有 thread + 最后活跃时间
"""

from fastapi import APIRouter
from pydantic import BaseModel

from app.agent.checkpointer import get_checkpointer

router = APIRouter(prefix="/api", tags=["threads"])


class ThreadInfo(BaseModel):
    """一个会话的摘要信息。"""

    thread_id: str
    #: 最后活跃时间（ISO 8601 格式）
    updated_at: str | None
    #: 消息条数
    message_count: int


@router.get("/threads")
async def list_threads() -> dict:
    """列出所有已知的会话。

    按最后活跃时间倒序 —— 最近用的排在最前面。
    """
    saver = await get_checkpointer()

    threads: list[ThreadInfo] = []
    async for checkpoint in saver.alist(None):
        config = checkpoint.config or {}
        thread_id = (config.get("configurable") or {}).get("thread_id")
        if not thread_id:
            continue

        values = checkpoint.checkpoint.get("channel_values") or {}
        messages = values.get("messages") or []

        # alist 默认按时间倒序，同一 thread 会有多个 checkpoint，
        # 所以只取第一个出现的（最新的那个）
        if any(t.thread_id == thread_id for t in threads):
            continue

        threads.append(
            ThreadInfo(
                thread_id=thread_id,
                updated_at=checkpoint.checkpoint.get("ts"),
                message_count=len(messages),
            )
        )

    return {"threads": [t.model_dump() for t in threads]}
