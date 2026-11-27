"""M4 记忆功能测试。

验证三件事：
  1. 历史对话提取正确（extract_conversation）
  2. 记忆接口能读能删
  3. 不同会话之间互相隔离
"""

import pytest
from fastapi.testclient import TestClient
from langchain_core.messages import AIMessage, HumanMessage

from app.agent.text import extract_conversation
from app.main import app

client = TestClient(app)


# ---------------------------------------------------------------------------
# 历史对话提取
# ---------------------------------------------------------------------------

def test_extract_conversation_single_turn() -> None:
    """只有一轮对话：当前问题就是唯一那条用户消息，历史为空。"""
    messages = [HumanMessage(content="你好")]
    current, history = extract_conversation(messages)
    assert current == "你好"
    assert history == []


def test_extract_conversation_two_turns() -> None:
    """两轮对话：当前问题是第二条，历史包含第一轮。"""
    messages = [
        HumanMessage(content="我叫小明"),
        AIMessage(content="你好小明"),
        HumanMessage(content="我叫什么"),
    ]
    current, history = extract_conversation(messages)
    assert current == "我叫什么"
    assert history == [
        {"role": "user", "content": "我叫小明"},
        {"role": "assistant", "content": "你好小明"},
    ]


def test_extract_conversation_skips_empty_ai_messages() -> None:
    """只有 tool_calls 没有正文的助手消息要跳过。"""
    messages = [
        HumanMessage(content="查天气"),
        AIMessage(content=""),
        HumanMessage(content="继续"),
    ]
    current, history = extract_conversation(messages)
    assert current == "继续"
    assert all(m["role"] != "assistant" for m in history)


def test_extract_conversation_no_human_message() -> None:
    """没有用户消息时返回空字符串。"""
    current, history = extract_conversation([AIMessage(content="你好")])
    assert current == ""
    assert history == [{"role": "assistant", "content": "你好"}]


# ---------------------------------------------------------------------------
# 记忆接口
# ---------------------------------------------------------------------------

def test_memory_of_unknown_thread_is_empty() -> None:
    """查一个不存在的会话，返回空列表而不是 404。"""
    r = client.get("/api/memory/does-not-exist-xyz")
    assert r.status_code == 200
    assert r.json() == {"thread_id": "does-not-exist-xyz", "messages": []}


def test_threads_list_is_available() -> None:
    """会话列表接口要能返回（哪怕是空的）。"""
    r = client.get("/api/threads")
    assert r.status_code == 200
    assert "threads" in r.json()


def test_clear_memory_is_idempotent() -> None:
    """清空不存在的会话也不该报错。"""
    r = client.delete("/api/memory/never-existed-abc")
    assert r.status_code == 200
    assert r.json()["cleared"] is True


def test_delete_thread_is_idempotent() -> None:
    """删不存在的会话也不该报错 —— 前端可以放心重试。"""
    r = client.delete("/api/threads/never-existed-xyz")
    assert r.status_code == 200
    assert r.json() == {"thread_id": "never-existed-xyz", "deleted": True}


def test_delete_thread_removes_its_memory() -> None:
    """删除会话后，它的记忆也查不到了。

    先往某个会话写一条消息，再删掉它，最后确认记忆为空。
    """
    import asyncio

    from langchain_core.messages import HumanMessage
    from langgraph.checkpoint.base import empty_checkpoint

    from app.agent.checkpointer import get_checkpointer

    thread_id = "test-delete-thread-001"

    async def _seed() -> None:
        saver = await get_checkpointer()
        checkpoint = empty_checkpoint()
        checkpoint["channel_values"] = {"messages": [HumanMessage(content="待删除的消息")]}
        await saver.aput(
            {
                "configurable": {
                    "thread_id": thread_id,
                    "checkpoint_ns": "",
                    "checkpoint_id": checkpoint["id"],
                }
            },
            checkpoint,
            {},
            {},
        )

    asyncio.run(_seed())

    # 确认写进去了
    r = client.get(f"/api/memory/{thread_id}")
    assert len(r.json()["messages"]) == 1

    # 删掉
    r = client.delete(f"/api/threads/{thread_id}")
    assert r.status_code == 200
    assert r.json()["deleted"] is True

    # 记忆没了
    r = client.get(f"/api/memory/{thread_id}")
    assert r.json()["messages"] == []


def test_chat_requires_thread_id() -> None:
    """M4 起 thread_id 必传，缺失要返回 422。"""
    r = client.post("/api/chat", json={"message": "hi"})
    assert r.status_code == 422
