"""M2 工具集合 —— 通过 bind_tools 暴露给 LLM。

这个文件做两件事：
  1. 用 _with_latency 包装每个工具，在返回值里注入 _latency_ms 耗时字段；
  2. 导出 ALL_TOOLS，这是 graph 唯一的工具入口。

为什么要包装而不在工具内部计时？
因为计时是"横切关注点"，包装属于正交实现 —— 三个工具函数一行不改就能拿到耗时。
"""

import time
from typing import Any

from langchain_core.tools import BaseTool, StructuredTool

from app.agent.tools.calculator import calculate
from app.agent.tools.search import web_search
from app.agent.tools.weather import get_weather

#: 耗时字段在返回字典里的键名。SSE 层会把它 pop 掉再发给前端。
LATENCY_KEY = "_latency_ms"


def _with_latency(tool: BaseTool) -> BaseTool:
    """给工具套一层计时，返回一个带耗时的新工具。

    注意同时传了 coroutine 和 func：
      - get_weather / web_search 是 async 的，走 _arun
      - calculate 是同步的，走 _run
    所以同步调用 async 工具会报 "does not support sync invocation"，
    测试里必须用 ainvoke。
    """

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
    """在工具返回值里塞入耗时（毫秒，保留一位小数）。"""
    latency_ms = round((time.perf_counter() - started) * 1000, 1)
    if isinstance(result, dict):
        return {**result, LATENCY_KEY: latency_ms}
    if isinstance(result, list):
        # 列表没法直接挂字段，包一层 dict
        return {"results": result, LATENCY_KEY: latency_ms}
    return result


#: 全部工具。graph.py 通过 bind_tools(ALL_TOOLS) 把它们交给模型。
#: 新增工具时只需要在这里加一行。
ALL_TOOLS = [_with_latency(tool) for tool in (get_weather, web_search, calculate)]

__all__ = ["ALL_TOOLS", "calculate", "get_weather", "web_search"]
