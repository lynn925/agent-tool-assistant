"""POST /api/chat —— M3 的 SSE 流式接口。

M1 返回普通 JSON，M2 改成 SSE，M3 在 M2 事件基础上加了计划相关事件。

事件协议见 PLAN.md §4：
  message_start  {id, role:"assistant", thread_id}      一条助手消息开始
  plan_update   {plan: TaskStep[]}                      M3：完整计划
  step_update   {id, status}                            M3：单步状态切换
  tool_call     {id, name, args}                        工具调用开始
  tool_result   {id, ok, result?, error?, latency_ms}    工具执行回执
  content_delta {delta}                                  最终答案的文本片段
  message_end   {finish_reason:"stop"|"error"}          助手消息结束
  error         {code, message, retriable}              全局错误
"""

import json
import uuid
from typing import AsyncIterator

from fastapi import APIRouter, HTTPException
from langchain_core.messages import HumanMessage
from langgraph.errors import GraphRecursionError
from pydantic import BaseModel, Field
from sse_starlette.sse import EventSourceResponse

from app.agent.graph import build_graph

router = APIRouter(prefix="/api", tags=["chat"])

#: 递归上限，防止计划无限循环。
RECURSION_LIMIT = 50


class ChatRequest(BaseModel):
    message: str = Field(..., min_length=1, max_length=4000)
    # M4 会真正用它做记忆持久化，M3 只是原样回传
    thread_id: str | None = None


def _sse(event: str, data: dict) -> dict:
    """封装一条 SSE 事件。

    sse_starlette 会把它序列化成：
        event: <event>
        data: <json>

    ensure_ascii=False 让中文直接以原文传输，不用转成 \\uXXXX。
    """
    return {"event": event, "data": json.dumps(data, ensure_ascii=False)}


def _step_payload(step: dict) -> dict:
    """把一个 TaskStep 转成前端要用的结构（去掉内部字段）。"""
    return {
        "id": step.get("id", ""),
        "description": step.get("description", ""),
        "tool": step.get("tool"),
        "args": step.get("args") or {},
        "status": step.get("status", "pending"),
        "result": step.get("result"),
        "error": step.get("error"),
    }


async def _stream_events(user_message: str, thread_id: str) -> AsyncIterator[dict]:
    """驱动整张图，把它的输出翻译成 SSE 事件。

    M3 只用 "custom" 模式 —— 接收节点里用 get_stream_writer() 推的事件：
      plan         完整计划
      step         单步状态变化
      tool_result  工具执行回执
      delta        最终答案的文本片段（aggregator 逐 token 推的）

    为什么不用 "messages" 模式：
      它会把 planner 的 JSON 输出也当成正文推给前端。
      M3 的正文只来自 aggregator，所以在节点内部自己 astream 更可控。
    """
    message_id = str(uuid.uuid4())
    # 第一条事件：告诉前端"助手消息开始了"
    yield _sse("message_start", {"id": message_id, "role": "assistant", "thread_id": thread_id})

    graph = build_graph()

    try:
        async for chunk in graph.astream(
            {"messages": [HumanMessage(content=user_message)]},
            stream_mode="custom",
            config={"recursion_limit": RECURSION_LIMIT},
        ):
            if not isinstance(chunk, dict):
                continue
            event = chunk.get("event")

            if event == "plan":
                # 完整计划：前端用它渲染 PlanPanel
                plan = chunk.get("plan") or []
                yield _sse(
                    "plan_update",
                    {"plan": [_step_payload(s) for s in plan]},
                )

            elif event == "step":
                # 单步状态变化
                step = chunk.get("step") or {}
                yield _sse(
                    "step_update",
                    {
                        "id": step.get("id", ""),
                        "status": step.get("status", "pending"),
                        "description": step.get("description", ""),
                        "tool": step.get("tool"),
                    },
                )

            elif event == "tool_result":
                # 工具执行回执
                payload = dict(chunk)
                payload.pop("event", None)
                yield _sse("tool_result", payload)

            elif event == "delta":
                # 最终答案的文本片段
                text = chunk.get("text") or ""
                if text:
                    yield _sse("content_delta", {"delta": text})

    except GraphRecursionError:
        # 执行轮次超限
        yield _sse(
            "error",
            {"code": "recursion_limit", "message": "执行轮次超限，已中止。", "retriable": False},
        )
        yield _sse("message_end", {"finish_reason": "error"})
        return
    except Exception as exc:
        # 其他未预期的异常（比如 LLM 接口挂了）
        yield _sse("error", {"code": "agent_failed", "message": str(exc), "retriable": True})
        yield _sse("message_end", {"finish_reason": "error"})
        return

    yield _sse("message_end", {"finish_reason": "stop"})


@router.post("/chat")
async def chat(req: ChatRequest) -> EventSourceResponse:
    """聊天接口，返回 SSE 流。"""
    # 局部导入：让缺 key 的报错在函数入口就抛出去（503），而不是等到流开始后
    from app.config import get_settings

    settings = get_settings()
    if not settings.openai_api_key:
        raise HTTPException(
            status_code=503,
            detail="OPENAI_API_KEY 未配置；请在 backend/.env 设置后重启。",
        )

    thread_id = req.thread_id or "m1-default"
    return EventSourceResponse(
        _stream_events(req.message, thread_id),
        media_type="text/event-stream",
    )
