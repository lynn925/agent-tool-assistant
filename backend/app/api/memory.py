"""M4 记忆接口 —— 查看/清空某个会话的历史。

对应 PLAN.md §6.2：
  GET    /api/memory/{thread_id}   返回消息历史
  DELETE /api/memory/{thread_id}   清空该会话的记忆
"""

from typing import Any

from fastapi import APIRouter, HTTPException
from langchain_core.messages import BaseMessage

from app.agent.checkpointer import get_checkpointer

router = APIRouter(prefix="/api/memory", tags=["memory"])


def _message_to_dict(message: BaseMessage) -> dict:
    """把 LangChain 消息对象转成前端要的字典。"""
    text = message.content if isinstance(message.content, str) else ""
    return {
        "type": message.type,  # human / ai
        "role": "user" if message.type == "human" else "assistant",
        "text": text,
    }


@router.get("/{thread_id}")
async def get_memory(thread_id: str) -> dict:
    """返回某个会话的历史消息。

    只取最新一个 checkpoint —— 它包含到目前为止的完整消息列表。
    """
    saver = await get_checkpointer()
    config = {"configurable": {"thread_id": thread_id}}

    checkpoint = await saver.aget_tuple(config)
    if checkpoint is None:
        # 会话不存在，返回空列表而不是 404，方便前端直接用
        return {"thread_id": thread_id, "messages": []}

    values = checkpoint.checkpoint.get("channel_values") or {}
    messages = values.get("messages") or []

    return {
        "thread_id": thread_id,
        "messages": [_message_to_dict(m) for m in messages if isinstance(m, BaseMessage)],
    }


@router.delete("/{thread_id}")
async def clear_memory(thread_id: str) -> dict:
    """清空某个会话的全部记忆。"""
    saver = await get_checkpointer()
    await saver.adelete_thread(thread_id)
    return {"thread_id": thread_id, "cleared": True}
