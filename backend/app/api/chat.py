"""POST /api/chat — M2 SSE endpoint.

Event protocol follows PLAN.md §4:
  message_start  {id, role:"assistant", thread_id}
  content_delta  {delta}
  tool_call     {id, name, args}
  tool_result   {id, ok, result?, error?, latency_ms}
  message_end   {finish_reason:"stop"|"error"}
  error         {code, message, retriable}
"""

import json
import uuid
from typing import AsyncIterator

from fastapi import APIRouter, HTTPException
from langchain_core.messages import AIMessage, AIMessageChunk, HumanMessage, ToolMessage
from langgraph.errors import GraphRecursionError
from pydantic import BaseModel, Field
from sse_starlette.sse import EventSourceResponse

from app.agent.graph import build_graph
from app.agent.tools import LATENCY_KEY

router = APIRouter(prefix="/api", tags=["chat"])

#: Guard against a model that keeps requesting tools forever.
RECURSION_LIMIT = 50

_THINK_OPEN = "<think>"
_THINK_CLOSE = "</think>"


class ChatRequest(BaseModel):
    message: str = Field(..., min_length=1, max_length=4000)
    thread_id: str | None = None  # M4 will persist; M2 echoes it back


class _ThinkFilter:
    """Strip `<think>...</think>` reasoning blocks from streamed text.

    MiniMax-style models emit their reasoning inline in the content stream.
    Tag markers can be split across chunks, so an incomplete trailing marker
    is held back until the next chunk arrives.
    """

    def __init__(self) -> None:
        self._inside = False
        self._pending = ""

    def feed(self, text: str) -> str:
        buf = self._pending + text
        self._pending = ""
        out: list[str] = []
        i = 0

        while i < len(buf):
            tag = _THINK_CLOSE if self._inside else _THINK_OPEN
            idx = buf.find(tag, i)
            if idx == -1:
                # No complete tag here — hold back a possible split marker.
                tail = self._partial_tag(buf[i:], tag)
                if not self._inside:
                    out.append(buf[i : len(buf) - len(tail)])
                self._pending = tail
                i = len(buf)
                continue

            if not self._inside:
                out.append(buf[i:idx])
            self._inside = not self._inside
            i = idx + len(tag)

        return "".join(out)

    def flush(self) -> str:
        """Return buffered text that never resolved into a tag."""
        tail = self._pending
        self._pending = ""
        return tail if not self._inside else ""

    @staticmethod
    def _partial_tag(rest: str, tag: str) -> str:
        """Longest suffix of `rest` that could be the start of `tag`."""
        for size in range(min(len(tag) - 1, len(rest)), 0, -1):
            if rest.endswith(tag[:size]):
                return rest[-size:]
        return ""


def _sse(event: str, data: dict) -> dict:
    return {"event": event, "data": json.dumps(data, ensure_ascii=False)}


def _decode_tool_content(content) -> dict:
    """Tool results arrive as JSON strings; normalise them to a dict."""
    if isinstance(content, dict):
        return content
    try:
        parsed = json.loads(content)
    except (TypeError, ValueError):
        return {"error": "tool_result_unparsable"}
    return parsed if isinstance(parsed, dict) else {"result": parsed}


async def _stream_events(user_message: str, thread_id: str) -> AsyncIterator[dict]:
    """Drive the graph and translate its output into SSE events."""
    message_id = str(uuid.uuid4())
    yield _sse("message_start", {"id": message_id, "role": "assistant", "thread_id": thread_id})

    graph = build_graph()
    think = _ThinkFilter()

    try:
        async for mode, chunk in graph.astream(
            {"messages": [HumanMessage(content=user_message)]},
            stream_mode=["messages", "updates"],
            config={"recursion_limit": RECURSION_LIMIT},
        ):
            if mode == "messages":
                message, _metadata = chunk
                if not isinstance(message, AIMessageChunk):
                    continue
                text = message.content if isinstance(message.content, str) else ""
                if not text:
                    continue
                delta = think.feed(text)
                if delta:
                    yield _sse("content_delta", {"delta": delta})

            elif mode == "updates":
                for node, update in chunk.items():
                    if not isinstance(update, dict):
                        continue
                    for message in update.get("messages", []) or []:
                        if node == "call_model" and isinstance(message, AIMessage):
                            for call in message.tool_calls or []:
                                yield _sse(
                                    "tool_call",
                                    {"id": call["id"], "name": call["name"], "args": call.get("args", {})},
                                )
                        elif node == "tools" and isinstance(message, ToolMessage):
                            payload = _decode_tool_content(message.content)
                            latency_ms = payload.pop(LATENCY_KEY, None)
                            ok = "error" not in payload
                            event: dict = {"id": message.tool_call_id, "ok": ok}
                            if ok:
                                event["result"] = payload
                            else:
                                event["error"] = payload.get("error")
                            if latency_ms is not None:
                                event["latency_ms"] = latency_ms
                            yield _sse("tool_result", event)

    except GraphRecursionError:
        yield _sse(
            "error",
            {"code": "recursion_limit", "message": "模型调用轮次超限，已中止。", "retriable": False},
        )
        yield _sse("message_end", {"finish_reason": "error"})
        return
    except Exception as exc:
        yield _sse("error", {"code": "agent_failed", "message": str(exc), "retriable": True})
        yield _sse("message_end", {"finish_reason": "error"})
        return

    trailing = think.flush()
    if trailing:
        yield _sse("content_delta", {"delta": trailing})
    yield _sse("message_end", {"finish_reason": "stop"})


@router.post("/chat")
async def chat(req: ChatRequest) -> EventSourceResponse:
    from app.config import get_settings  # local import to surface 503 fast

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
