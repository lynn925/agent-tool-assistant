"""M5 的 executor 节点行为测试。

重点验证「失败后继续执行剩余步骤」这个已确认的语义，以及
failed / skipped 两种状态的区分。

这些测试不调真实模型和真实网络 —— 工具被替换成假的，
所以跑得快且稳定。
"""

import asyncio

import httpx
import openai
import pytest
from langchain_core.tools import tool
from tenacity import wait_none

from app.agent import nodes
from app.agent.nodes import executor_node, should_continue
from app.agent.tools import ALL_TOOLS


@pytest.fixture(autouse=True)
def _test_env(monkeypatch: pytest.MonkeyPatch):
    """准备测试环境：

    1. get_stream_writer 在 LangGraph 的 runnable 上下文里才有，
       单元测试里直接调节点会抛 RuntimeError —— 这里换成收集器。
    2. 跳过退避等待，不然测试套件要睡掉十几秒。
    """
    events: list[dict] = []
    monkeypatch.setattr(nodes, "get_stream_writer", lambda: events.append)

    original = nodes.run_tool_with_retry

    async def _no_backoff(tool, args, **kwargs):
        kwargs["wait"] = wait_none()
        return await original(tool, args, **kwargs)

    monkeypatch.setattr(nodes, "run_tool_with_retry", _no_backoff)
    return events


def _plan_step(
    step_id: str = "step-1",
    tool: str | None = "calculate",
    args: dict | None = None,
) -> dict:
    """构造一个计划步骤。"""
    return {
        "id": step_id,
        "description": "测试步骤",
        "tool": tool,
        "args": args if args is not None else {"expression": "1+1"},
        "status": "pending",
        "result": None,
        "error": None,
        "retry": 0,
    }


def _run_executor(plan: list[dict], index: int = 0) -> dict:
    """跑一次 executor 节点（不带 stream writer，事件会写不出来）。"""
    state = {"plan": plan, "current_step": index}
    return asyncio.run(executor_node(state))


# ---------------------------------------------------------------------------
# 步骤状态
# ---------------------------------------------------------------------------

def test_successful_step_is_done() -> None:
    """成功执行的步骤标记为 done。"""
    result = _run_executor([_plan_step()])
    step = result["plan"][0]
    assert step["status"] == "done"
    assert step["error"] is None
    assert step["result"]["result"] == "2"


def test_tool_error_marks_step_failed() -> None:
    """工具返回错误字典 → 标记 failed（红），不是 skipped。"""

    @tool
    def failing(city: str) -> dict:
        """总是失败。"""
        return {"error": "city_not_found"}

    original = ALL_TOOLS[:]
    try:
        ALL_TOOLS.clear()
        ALL_TOOLS.append(failing)
        result = _run_executor([_plan_step(tool="failing", args={"city": "x"})])
    finally:
        ALL_TOOLS.clear()
        ALL_TOOLS.extend(original)

    step = result["plan"][0]
    assert step["status"] == "failed"
    assert step["error"] == "city_not_found"


def test_unknown_tool_marks_step_skipped() -> None:
    """工具不存在 → 标记 skipped（黄），因为这一步根本没法执行。"""
    result = _run_executor([_plan_step(tool="no_such_tool")])
    step = result["plan"][0]
    assert step["status"] == "skipped"
    assert step["error"] == "unknown_tool"


def test_invalid_arguments_mark_step_skipped() -> None:
    """参数校验失败 → skipped（这步没法执行，不该重试也不该算 failed）。"""
    # city 传成了数字，pydantic 会校验失败
    result = _run_executor(
        [_plan_step(tool="get_weather", args={"city": 12345})]
    )
    step = result["plan"][0]
    assert step["status"] == "skipped"
    assert "invalid_arguments" in step["error"]


def test_step_without_tool_is_done() -> None:
    """不需要工具的步骤直接完成。"""
    result = _run_executor([_plan_step(tool=None)])
    step = result["plan"][0]
    assert step["status"] == "done"


# ---------------------------------------------------------------------------
# 任务层：失败不阻塞后续步骤
# ---------------------------------------------------------------------------

def test_failed_step_does_not_block_following_steps() -> None:
    """已确认的语义：某步失败后，后续步骤照常执行。

    这是 M5 相对 M3 的一个变化 —— M3 把失败也标成 skipped，
    语义上分不清「失败了」和「没执行」。
    """
    plan = [_plan_step("step-1"), _plan_step("step-2"), _plan_step("step-3")]

    # 第一步失败
    plan[0]["status"] = "failed"
    assert should_continue({"plan": plan, "current_step": 1}) == "executor"

    # 全部执行完才去汇总
    assert should_continue({"plan": plan, "current_step": 3}) == "aggregator"


def test_skipped_step_does_not_block_following_steps() -> None:
    """跳过的步骤同样不阻塞后续。"""
    plan = [_plan_step("step-1"), _plan_step("step-2")]
    plan[0]["status"] = "skipped"
    assert should_continue({"plan": plan, "current_step": 1}) == "executor"


# ---------------------------------------------------------------------------
# 重试计数透传
# ---------------------------------------------------------------------------

def test_retry_count_is_recorded_in_step() -> None:
    """重试次数要写进 step，前端才能显示「重试 N 次」。"""
    state = {"n": 0}

    @tool
    def flaky(city: str) -> dict:
        """前两次超时，第三次成功。"""
        state["n"] += 1
        if state["n"] < 3:
            return {"error": "timeout"}
        return {"city": city, "temp_c": 20}

    original = ALL_TOOLS[:]
    try:
        ALL_TOOLS.clear()
        ALL_TOOLS.append(flaky)
        result = _run_executor([_plan_step(tool="flaky", args={"city": "x"})])
    finally:
        ALL_TOOLS.clear()
        ALL_TOOLS.extend(original)

    step = result["plan"][0]
    assert step["status"] == "done"
    assert step["retry"] == 2


def test_exhausted_retries_mark_failed_with_retry_count() -> None:
    """重试耗尽 → failed，且记录重试次数。"""

    @tool
    def always_timeout(city: str) -> dict:
        """一直超时。"""
        return {"error": "timeout"}

    original = ALL_TOOLS[:]
    try:
        ALL_TOOLS.clear()
        ALL_TOOLS.append(always_timeout)
        result = _run_executor([_plan_step(tool="always_timeout", args={"city": "x"})])
    finally:
        ALL_TOOLS.clear()
        ALL_TOOLS.extend(original)

    step = result["plan"][0]
    assert step["status"] == "failed"
    assert step["error"] == "timeout"
    assert step["retry"] == 3  # 配置默认重试 3 次


def test_transient_exception_is_retried_then_fails() -> None:
    """工具抛 transient 异常 → 会重试；耗尽后标 failed。"""
    state = {"n": 0}

    @tool
    def boom(city: str) -> dict:
        """抛连接错误。"""
        state["n"] += 1
        raise httpx.ConnectError("network down")

    original = ALL_TOOLS[:]
    try:
        ALL_TOOLS.clear()
        ALL_TOOLS.append(boom)
        result = _run_executor([_plan_step(tool="boom", args={"city": "x"})])
    finally:
        ALL_TOOLS.clear()
        ALL_TOOLS.extend(original)

    step = result["plan"][0]
    assert step["status"] == "failed"
    assert state["n"] == 4  # 首次 + 3 次重试
    assert step["retry"] == 3


# ---------------------------------------------------------------------------
# aggregator 的流式重试
# ---------------------------------------------------------------------------

def test_aggregator_retries_before_streaming_any_content(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """aggregator 还没吐正文时失败 → 应该重试。

    这是聚合器最容易被忽略的坑：如果已经推了 token 给前端再重试，
    前端会收到重复的内容。所以只能在「还没开始输出」时重试。
    """
    state = {"n": 0}

    class FakeChunk:
        def __init__(self, content: str) -> None:
            self.content = content

    class FakeModel:
        async def astream(self, messages):
            state["n"] += 1
            if state["n"] < 3:
                raise httpx.ConnectError("network down")
            yield FakeChunk("你好")

    monkeypatch.setattr(nodes, "_model", lambda *a, **k: FakeModel())
    monkeypatch.setattr(nodes.asyncio, "sleep", _no_sleep)

    events: list[dict] = []
    monkeypatch.setattr(nodes, "get_stream_writer", lambda: events.append)

    result = asyncio.run(
        nodes.aggregator_node({"messages": [], "plan": [], "current_step": 0})
    )

    assert result["final_answer"] == "你好"
    assert state["n"] == 3
    # 应该有两条 retry 事件
    retries = [e for e in events if e.get("event") == "retry"]
    assert len(retries) == 2
    assert retries[0]["layer"] == "llm"
    assert retries[0]["stage"] == "aggregator"


def test_aggregator_does_not_retry_after_content_started(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """已经吐过正文后失败 → 不重试，直接抛。

    重试会导致前端收到重复内容，宁可失败也不能重复。
    """

    class FakeChunk:
        def __init__(self, content: str) -> None:
            self.content = content

    class FakeModel:
        async def astream(self, messages):
            yield FakeChunk("部分内容")
            raise httpx.ConnectError("network down")

    monkeypatch.setattr(nodes, "_model", lambda *a, **k: FakeModel())
    monkeypatch.setattr(nodes.asyncio, "sleep", _no_sleep)
    monkeypatch.setattr(nodes, "get_stream_writer", lambda: lambda e: None)

    with pytest.raises(httpx.ConnectError):
        asyncio.run(
            nodes.aggregator_node({"messages": [], "plan": [], "current_step": 0})
        )


def test_aggregator_does_not_retry_permanent_errors(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """鉴权失败这类永久错误 → 不重试，直接抛。"""
    state = {"n": 0}

    # 构造一个带 request 的 401 响应（openai 的异常要求 response.request 存在）
    request = httpx.Request("POST", "https://api.example.com/v1/chat/completions")
    response = httpx.Response(401, request=request)

    class FakeModel:
        async def astream(self, messages):
            state["n"] += 1
            # 必须是 async generator：先 yield 一个空的再抛，
            # 否则 astream 返回的是 coroutine 而不是 async iterator。
            if False:
                yield None
            raise openai.AuthenticationError(
                "bad key", response=response, body=None
            )

    monkeypatch.setattr(nodes, "_model", lambda *a, **k: FakeModel())
    monkeypatch.setattr(nodes.asyncio, "sleep", _no_sleep)
    monkeypatch.setattr(nodes, "get_stream_writer", lambda: lambda e: None)

    with pytest.raises(openai.AuthenticationError):
        asyncio.run(
            nodes.aggregator_node({"messages": [], "plan": [], "current_step": 0})
        )

    assert state["n"] == 1  # 一次都没重试


async def _no_sleep(_seconds: float) -> None:
    """跳过退避等待的假 sleep。"""
    return None
