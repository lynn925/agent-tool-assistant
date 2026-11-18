"""M2 tools exposed to the LLM via `bind_tools`.

Each tool returns a plain dict so failures can be reported as
`{"error": "<code>"}` instead of raising, per the PLAN.md M2 contract.
Every tool is wrapped with a latency timer that injects `_latency_ms`
into the returned payload so the SSE layer can report it.
"""

import time
from typing import Any

from langchain_core.tools import BaseTool, StructuredTool

from app.agent.tools.calculator import calculate
from app.agent.tools.search import web_search
from app.agent.tools.weather import get_weather

LATENCY_KEY = "_latency_ms"


def _with_latency(tool: BaseTool) -> BaseTool:
    """Wrap a tool so its result carries the execution latency."""

    async def _arun(**kwargs: Any) -> Any:
        started = time.perf_counter()
        result = await tool.ainvoke(kwargs)
        return _stamp(result, started)

    def _run(**kwargs: Any) -> Any:
        started = time.perf_counter()
        result = tool.invoke(kwargs)
        return _stamp(result, started)

    return StructuredTool(
        name=tool.name,
        description=tool.description,
        args_schema=tool.args_schema,
        coroutine=_arun,
        func=_run,
    )


def _stamp(result: Any, started: float) -> Any:
    latency_ms = round((time.perf_counter() - started) * 1000, 1)
    if isinstance(result, dict):
        return {**result, LATENCY_KEY: latency_ms}
    if isinstance(result, list):
        return {"results": result, LATENCY_KEY: latency_ms}
    return result


ALL_TOOLS = [_with_latency(tool) for tool in (get_weather, web_search, calculate)]

__all__ = ["ALL_TOOLS", "calculate", "get_weather", "web_search"]
