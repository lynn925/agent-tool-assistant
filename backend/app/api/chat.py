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

M5 新增：
  retry         {layer, stage, attempt, max_attempts, message}  正在重试
  tool_result 多了 retry 字段 —— 重试几次后成功的
"""

import json
import uuid
from typing import Any, AsyncIterator

from fastapi import APIRouter, HTTPException
from langchain_core.messages import HumanMessage
from langgraph.errors import GraphRecursionError
from pydantic import BaseModel, Field
from sse_starlette.sse import EventSourceResponse

from app.agent.checkpointer import get_checkpointer
from app.agent.graph import build_graph_with_memory
from app.agent.retry import is_transient

router = APIRouter(prefix="/api", tags=["chat"])

#: 递归上限，防止计划无限循环。
RECURSION_LIMIT = 50


class ChatRequest(BaseModel):
    message: str = Field(..., min_length=1, max_length=4000)
    #: 会话 ID。M4 起必传 —— 它决定读写哪个会话的记忆。
    #: 传空字符串会返回 400。
    thread_id: str = Field(..., min_length=1, max_length=100)

    # M6：可选的运行时覆盖（来自前端的设置页）。
    # 不传就用后端 .env 里的全局默认值 —— 所以旧客户端不受影响。
    #: 模型名。传空字符串视为不覆盖。
    model: str | None = Field(default=None, max_length=100)
    #: 聚合器温度。0~1。
    temperature: float | None = Field(default=None, ge=0.0, le=1.0)
    #: 最大重试次数（不含首次尝试）。0~5。
    retry_max_attempts: int | None = Field(default=None, ge=0, le=5)


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
        # M5：这步重试了几次
        "retry": step.get("retry", 0),
    }


def _friendly_error(exc: Exception) -> str:
    """把底层异常翻译成用户能看懂、能行动的信息。

    M6：设置页能改模型名了，所以「模型不存在」是最常见的错误。
    上游返回的是这种：
        OpenAIInvalidRequestError: Error code: 400 - {... 'invalid params,
        unknown model 'gpt-4o-mini' (2013)' ...}
    直接甩给用户毫无意义 —— 要告诉他「模型名不对，去设置页改一下」。
    """
    # provider 没配 key —— 最常见的「选了个用不了的模型」
    from app.agent.providers import ProviderNotConfigured

    if isinstance(exc, ProviderNotConfigured):
        return str(exc)

    raw = str(exc)

    # 模型不存在 —— 设置页填错了模型名
    if "unknown model" in raw:
        import re

        m = re.search(r"unknown model '([^']+)'", raw)
        name = m.group(1) if m else "该模型"
        return (
            f"模型「{name}」不可用。"
            "请到设置页确认模型名是否正确，"
            "或改回当前 provider 支持的模型。"
        )

    # 鉴权失败
    if "Incorrect API key" in raw or "invalid_api_key" in raw:
        return "API Key 无效，请检查 backend/.env 里的 OPENAI_API_KEY。"

    # 额度用尽
    if "insufficient" in raw.lower() or "quota" in raw.lower():
        return "API 额度不足，请充值或更换服务商。"

    # 其它错误：保留原始信息但去掉冗长的前缀
    return f"{type(exc).__name__}: {raw}"


async def _stream_events(
    user_message: str,
    thread_id: str,
    overrides: ChatRequest | None = None,
) -> AsyncIterator[dict]:
    """驱动整张图，把它的输出翻译成 SSE 事件。

    M3 只用 "custom" 模式 —— 接收节点里用 get_stream_writer() 推的事件：
      plan         完整计划
      step         单步状态变化
      tool_result  工具执行回执
      delta        最终答案的文本片段（aggregator 逐 token 推的）

    为什么不用 "messages" 模式：
      它会把 planner 的 JSON 输出也当成正文推给前端。
      M3 的正文只来自 aggregator，所以在节点内部自己 astream 更可控。

    M4 的变化：图带上了 checkpointer，config 里指定 thread_id，
    于是这个会话的历史消息会被自动带上，模型能记住之前聊过什么。

    M6 的变化：运行时覆盖（模型/温度/重试次数）放进 configurable。
    这样每个请求独立生效 —— 不会因为改了一次设置就污染全局，
    也不会让并发请求互相干扰。
    """
    message_id = str(uuid.uuid4())
    # 第一条事件：告诉前端"助手消息开始了"
    yield _sse("message_start", {"id": message_id, "role": "assistant", "thread_id": thread_id})

    checkpointer = await get_checkpointer()
    graph = build_graph_with_memory(checkpointer)

    # 只把真正传了的值放进 configurable ——
    # 没传的保持 None，节点里就会回退到全局默认值。
    configurable: dict[str, Any] = {"thread_id": thread_id}
    if overrides.model:
        configurable["model"] = overrides.model
    if overrides.temperature is not None:
        configurable["temperature"] = overrides.temperature
    if overrides.retry_max_attempts is not None:
        configurable["retry_max_attempts"] = overrides.retry_max_attempts

    try:
        async for chunk in graph.astream(
            {"messages": [HumanMessage(content=user_message)]},
            stream_mode="custom",
            config={
                "recursion_limit": RECURSION_LIMIT,
                "configurable": configurable,
            },
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
                        # M5：错误原因和重试次数 —— 前端要靠它们显示
                        # 「执行失败（xxx），已重试 N 次」
                        "error": step.get("error"),
                        "retry": step.get("retry", 0),
                    },
                )

            elif event == "tool_result":
                # 工具执行回执
                payload = dict(chunk)
                payload.pop("event", None)
                yield _sse("tool_result", payload)

            elif event == "retry":
                # M5：正在重试。前端据此显示「重试中…」的提示
                payload = dict(chunk)
                payload.pop("event", None)
                yield _sse("retry", payload)

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
        # M5：区分两类错误 ——
        #   transient（如限流、连接失败）：重试层已经自动重试过，
        #     但还是没成功。属于服务端临时问题，用户稍后重发可能就好了 → retriable=True
        #   permanent（如鉴权失败、请求不合法）：重发也没用 → retriable=False
        retriable = is_transient(exc)
        yield _sse(
            "error",
            {
                "code": "agent_failed" if retriable else "agent_error",
                "message": _friendly_error(exc),
                "retriable": retriable,
            },
        )
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

    return EventSourceResponse(
        _stream_events(req.message, req.thread_id, req),
        media_type="text/event-stream",
    )
