"""M5 错误恢复（重试）测试（对应 PLAN.md §7）。

重点验证四件事：
  1. 错误分类 —— 哪些该重试，哪些不该（重试判定是 M5 的核心）
  2. 重试行为 —— 退避重试、次数上限、耗尽后的结果
  3. 步骤状态 —— failed / skipped 的区别（已与用户确认）
  4. 任务层 —— 某步失败不阻塞后续步骤
"""

import asyncio

import httpx
import openai
import pydantic
import pytest
from langchain_core.tools import tool
from tenacity import wait_none

from app.agent.retry import (
    is_transient,
    is_transient_tool_result,
    run_tool_with_retry,
    run_with_retry,
)

#: 测试里跳过退避等待 —— 否则光重试测试就要睡掉十几秒。
#: 被测的逻辑是「重试几次」「结果对不对」，不是「等了多久」。
NO_WAIT = wait_none()


# ---------------------------------------------------------------------------
# 错误分类
# ---------------------------------------------------------------------------

@pytest.mark.parametrize(
    "exc",
    [
        httpx.ConnectTimeout("timeout"),
        httpx.ReadTimeout("timeout"),
        httpx.ConnectError("conn"),
        httpx.RemoteProtocolError("proto"),
        TimeoutError("timeout"),
        openai.APITimeoutError.__new__(openai.APITimeoutError),
        openai.APIConnectionError.__new__(openai.APIConnectionError),
        openai.RateLimitError.__new__(openai.RateLimitError),
        openai.InternalServerError.__new__(openai.InternalServerError),
    ],
)
def test_transient_errors_are_retried(exc: BaseException) -> None:
    """网络抖动、限流、5xx 这些临时性错误都该重试。"""
    assert is_transient(exc) is True


@pytest.mark.parametrize(
    "exc",
    [
        ValueError("some bug"),
        RuntimeError("some bug"),
        pydantic.ValidationError.from_exception_data("x", []),
        openai.BadRequestError.__new__(openai.BadRequestError),
        openai.AuthenticationError.__new__(openai.AuthenticationError),
        openai.PermissionDeniedError.__new__(openai.PermissionDeniedError),
    ],
)
def test_permanent_errors_are_not_retried(exc: BaseException) -> None:
    """参数写错、鉴权失败这类永久错误不该重试 —— 重试也没用。"""
    assert is_transient(exc) is False


# ---------------------------------------------------------------------------
# 工具返回值分类
# ---------------------------------------------------------------------------

@pytest.mark.parametrize(
    "result",
    [
        {"error": "timeout"},
        {"error": "upstream_error"},
        {"error": "upstream_rate_limited"},
    ],
)
def test_transient_tool_results(result: dict) -> None:
    """工具返回的临时性错误码该重试。"""
    assert is_transient_tool_result(result) is True


@pytest.mark.parametrize(
    "result",
    [
        {"error": "city_not_found"},  # 城市不存在，再查一百次还是不存在
        {"error": "forbidden_keyword"},  # 表达式有黑名单词
        {"error": "syntax_error"},
        {"error": "evaluation_error"},
        {"error": "serpapi_key_missing"},  # 没配 key
        {"error": "serpapi_error"},
        {"city": "Shanghai", "temp_c": 20},  # 成功结果
        ["a", "b"],  # 非字典
        {"temp_c": 20},  # 没有 error 字段
    ],
)
def test_permanent_tool_results(result: object) -> None:
    """永久性错误码和正常结果都不该重试。"""
    assert is_transient_tool_result(result) is False


# ---------------------------------------------------------------------------
# 重试行为
# ---------------------------------------------------------------------------

def test_retry_succeeds_after_transient_failures() -> None:
    """前两次失败、第三次成功 —— 最终要拿到结果，且重试次数如实记录。"""
    calls = {"n": 0}

    async def flaky() -> str:
        calls["n"] += 1
        if calls["n"] < 3:
            raise httpx.ConnectError("boom")
        return "success"

    outcome = asyncio.run(run_with_retry(flaky, max_retries=3, wait=NO_WAIT))

    assert outcome.ok is True
    assert outcome.result == "success"
    assert outcome.report.retries == 2
    assert calls["n"] == 3


def test_retry_gives_up_after_max_retries() -> None:
    """一直失败 —— 重试到上限就放弃，把原始异常交回去。"""
    calls = {"n": 0}

    async def always_fail() -> str:
        calls["n"] += 1
        raise httpx.ConnectError("boom")

    outcome = asyncio.run(run_with_retry(always_fail, max_retries=3, wait=NO_WAIT))

    assert outcome.ok is False
    assert isinstance(outcome.error, httpx.ConnectError)
    # 首次 + 3 次重试 = 4 次调用
    assert calls["n"] == 4
    assert outcome.report.retries == 3


def test_permanent_error_is_not_retried() -> None:
    """永久错误只调用一次，不浪费时间和额度。"""
    calls = {"n": 0}

    async def bad_request() -> str:
        calls["n"] += 1
        raise ValueError("bad")

    outcome = asyncio.run(run_with_retry(bad_request, max_retries=3, wait=NO_WAIT))

    assert outcome.ok is False
    assert calls["n"] == 1
    assert outcome.report.retries == 0


def test_retry_callback_is_invoked_per_retry() -> None:
    """每次重试都要回调一次，前端才能实时显示重试进度。"""
    seen: list[int] = []

    async def always_fail() -> str:
        raise httpx.ConnectError("boom")

    asyncio.run(
        run_with_retry(
            always_fail,
            max_retries=2,
            on_retry=lambda s: seen.append(s.attempt_number),
            wait=NO_WAIT,
        )
    )

    assert len(seen) == 2


# ---------------------------------------------------------------------------
# 工具层重试
# ---------------------------------------------------------------------------

def test_tool_retries_on_transient_error_result() -> None:
    """工具返回 {"error": "timeout"} 时要重试，成功后拿到正常结果。"""
    state = {"n": 0}

    @tool
    def flaky(city: str) -> dict:
        """前两次超时，第三次成功。"""
        state["n"] += 1
        if state["n"] < 3:
            return {"error": "timeout"}
        return {"city": city, "temp_c": 20}

    outcome = asyncio.run(
        run_tool_with_retry(flaky, {"city": "上海"}, max_retries=3, wait=NO_WAIT)
    )

    assert outcome.ok is True
    assert outcome.report.retries == 2
    assert state["n"] == 3
    assert outcome.result["temp_c"] == 20


def test_tool_exhausted_retry_keeps_error_payload() -> None:
    """重试耗尽后，错误码不能丢 —— 否则前端只知道"失败了"却不知道为啥。"""
    state = {"n": 0}

    @tool
    def always_timeout(city: str) -> dict:
        """一直超时。"""
        state["n"] += 1
        return {"error": "timeout"}

    outcome = asyncio.run(
        run_tool_with_retry(always_timeout, {"city": "x"}, max_retries=2, wait=NO_WAIT)
    )

    assert state["n"] == 3  # 首次 + 2 次重试
    assert outcome.report.retries == 2
    # 关键：错误字典必须原样返回，而不是被包成 RetryError
    assert outcome.result == {"error": "timeout"}


def test_tool_permanent_error_result_is_not_retried() -> None:
    """工具返回不可重试的错误码时，一次都不该重试。"""
    state = {"n": 0}

    @tool
    def not_found(city: str) -> dict:
        """城市不存在。"""
        state["n"] += 1
        return {"error": "city_not_found"}

    outcome = asyncio.run(
        run_tool_with_retry(not_found, {"city": "x"}, max_retries=3, wait=NO_WAIT)
    )

    assert state["n"] == 1
    assert outcome.report.retries == 0
    assert outcome.result == {"error": "city_not_found"}
