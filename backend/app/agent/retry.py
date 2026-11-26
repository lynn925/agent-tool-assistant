"""M5 错误恢复 —— 重试策略核心。

三个层次的错误处理（对应 PLAN.md §7.1）：

  工具层   transient 错误（超时 / 连接失败 / 限流 / 5xx）→ 指数退避重试，最多 3 次
  LLM 层   同工具层
  节点层   永久错误（参数非法 / 黑名单命中）→ 立即失败，**不**重试

关键设计：区分「可重试」和「不可重试」。
  可重试：网络抖动、限流、上游 5xx —— 再试一次可能就好了
  不可重试：参数写错、表达式有黑名单词 —— 再试一万次也是同样的错

所以重试判定不靠「捕获所有异常」，而是白名单式的 transient 判定。
"""

from __future__ import annotations

import asyncio
from dataclasses import dataclass, field
from typing import Any, Awaitable, Callable, TypeVar

import httpx
import openai
import pydantic
from tenacity import (
    AsyncRetrying,
    RetryCallState,
    retry_if_exception,
    retry_if_result,
    wait_exponential,
)

from app.config import get_settings

T = TypeVar("T")

#: 指数退避的基数：第 1 次等 1s，第 2 次等 2s，第 3 次等 4s。
WAIT_MULTIPLIER = 1.0

#: 单次退避的最长等待时间，防止指数爆炸。
WAIT_MAX = 8.0


# ---------------------------------------------------------------------------
# 错误分类
# ---------------------------------------------------------------------------

#: LLM 层的 transient 异常。
#:
#: openai 的异常层次（已核实）：
#:   APITimeoutError  → APIConnectionError → APIError
#:   RateLimitError   → APIStatusError   → APIError
#:   InternalServerError → APIStatusError → APIError
#:
#: 注意 APITimeoutError 是 APIConnectionError 的子类，所以只列父类即可覆盖。
LLM_TRANSIENT_EXCEPTIONS: tuple[type[BaseException], ...] = (
    openai.APITimeoutError,
    openai.APIConnectionError,
    openai.RateLimitError,
    openai.InternalServerError,
)

#: 工具层的 transient 异常。
#:
#: httpx 是工具层用 httpx 直接发的请求，异常类型和 openai 不同。
#: asyncio.TimeoutError 是内置 TimeoutError 的别名，Python 3.11 起两者相同。
TOOL_TRANSIENT_EXCEPTIONS: tuple[type[BaseException], ...] = (
    httpx.TimeoutException,
    httpx.ConnectError,
    httpx.ReadError,
    httpx.RemoteProtocolError,
    asyncio.TimeoutError,
)

#: 永久错误 —— 命中就不该重试。
#:
#: pydantic.ValidationError：工具入参校验失败（比如 city 传成了数字）
#: openai.BadRequestError：请求本身不合法，重试也不会变
#: openai.AuthenticationError / PermissionDeniedError：鉴权问题，重试只是浪费额度
PERMANENT_EXCEPTIONS: tuple[type[BaseException], ...] = (
    pydantic.ValidationError,
    openai.BadRequestError,
    openai.AuthenticationError,
    openai.PermissionDeniedError,
    openai.NotFoundError,
)


def is_transient(exc: BaseException) -> bool:
    """判断异常是否值得重试。

    规则：
      1. 永久错误优先 —— 即使它也是 transient 的子类也不重试；
      2. 命中 transient 白名单 → 重试；
      3. 其他 → 不重试。
    """
    if isinstance(exc, PERMANENT_EXCEPTIONS):
        return False
    if isinstance(exc, LLM_TRANSIENT_EXCEPTIONS + TOOL_TRANSIENT_EXCEPTIONS):
        return True
    return False


def is_transient_tool_result(result: Any) -> bool:
    """判断工具**返回值**是否代表一次可重试的失败。

    三个工具都自己吞掉异常、返回 {"error": "..."}，所以重试判定
    必须同时看返回值，不能只看异常。

    可重试的错误码（上游临时问题）：
      timeout        请求超时
      upstream_error 上游 5xx / 网络异常
      upstream_rate_limited 上游限流
      rag_timeout    RAG 检索超时
      rag_unavailable RAG 服务连不上

    不可重试的错误码（重试也没用）：
      city_not_found 城市不存在 —— 再查一百次还是不存在
      forbidden_keyword / syntax_error / evaluation_error 表达式本身有问题
      serpapi_key_missing 没配 key
      serpapi_error   SerpAPI 额度用尽等
      rag_not_configured 没配 RAG 地址
      empty_query     查询词是空的
    """
    if not isinstance(result, dict):
        return False
    error = result.get("error")
    if not isinstance(error, str):
        return False
    return error in {
        "timeout",
        "upstream_error",
        "upstream_rate_limited",
        "rag_timeout",
        "rag_unavailable",
    }


# ---------------------------------------------------------------------------
# 重试执行器
# ---------------------------------------------------------------------------

@dataclass
class RetryReport:
    """一次重试过程的统计信息。"""

    #: 实际重试了几次（首次成功是 0）
    retries: int = 0


@dataclass
class RetryOutcome:
    """重试的最终结果。

    成功时 result 有值、error 为 None；
    失败时 result 为 None、error 是原始异常。
    """

    result: Any = None
    error: BaseException | None = None
    report: RetryReport = field(default_factory=RetryReport)

    @property
    def ok(self) -> bool:
        return self.error is None


def _max_retries(default: int | None = None) -> int:
    """确定这次调用的重试次数上限。

    优先级：请求级覆盖（M6 设置页）> 全局配置 > 传入的默认值。

    请求级覆盖从 LangGraph 的 configurable 里读 —— 这样每个请求独立，
    不会污染全局配置。
    """
    if default is not None:
        return default

    # 请求级覆盖
    try:
        from langgraph.config import get_config

        overrides = (get_config().get("configurable") or {})
        value = overrides.get("retry_max_attempts")
        if value is not None:
            return int(value)
    except Exception:
        # 不在图里跑（单元测试直接调）就跳到全局配置
        pass

    return get_settings().retry_max_attempts


def _build_retrying(
    *,
    max_retries: int,
    on_retry: Callable[[RetryCallState], None] | None = None,
    wait: Any = None,
) -> AsyncRetrying:
    """构造 tenacity 的 AsyncRetrying。

    stop_after_attempt(max_retries + 1)：首次 + N 次重试。
    wait_exponential：指数退避 1s → 2s → 4s。
    retry_if_exception(is_transient)：只对 transient 异常重试。

    wait 参数用于测试时注入 wait_none()，避免真的睡几秒。
    """
    from tenacity import stop_after_attempt

    if wait is None:
        wait = wait_exponential(multiplier=WAIT_MULTIPLIER, max=WAIT_MAX)

    return AsyncRetrying(
        stop=stop_after_attempt(max_retries + 1),
        wait=wait,
        retry=retry_if_exception(is_transient),
        reraise=True,
        before_sleep=on_retry,
    )


async def run_with_retry(
    fn: Callable[[], Awaitable[T]],
    *,
    max_retries: int | None = None,
    on_retry: Callable[[RetryCallState], None] | None = None,
    wait: Any = None,
) -> RetryOutcome:
    """执行一个异步函数，对 transient 错误做指数退避重试。

    与 tenacity 的 retry_if_exception 不同，这里**不抛异常**，
    而是把结果包成 RetryOutcome —— 上层（executor_node）需要知道
    "重试了几次、最终成功还是失败"，而不是靠捕获异常反推。

    参数：
      fn          要调用的异步函数
      max_retries 重试次数上限，默认读配置
      on_retry    每次准备重试前的回调（用于实时推送 SSE 事件）
      wait        退避策略，测试时可传 wait_none() 跳过等待
    """
    max_retries = _max_retries(max_retries)

    report = RetryReport()

    def _handle_retry(state: RetryCallState) -> None:
        """重试前的钩子：记录次数并通知调用方。

        before_sleep 每次「即将发生一次重试」时调用一次，
        而重试耗尽时不会再调它 —— 所以数它的调用次数就是实际重试次数。
        """
        report.retries += 1
        if on_retry is not None:
            on_retry(state)

    retrying = _build_retrying(
        max_retries=max_retries, on_retry=_handle_retry, wait=wait
    )

    try:
        result = await retrying(fn)
    except BaseException as exc:  # noqa: BLE001 —— 统一转成 outcome
        # reraise=True，所以最后一次失败会抛到这里
        return RetryOutcome(result=None, error=exc, report=report)

    return RetryOutcome(result=result, error=None, report=report)


async def run_tool_with_retry(
    tool: Any,
    args: dict[str, Any],
    *,
    max_retries: int | None = None,
    on_retry: Callable[[RetryCallState], None] | None = None,
    wait: Any = None,
) -> RetryOutcome:
    """调用一个 LangChain 工具，对 transient 失败重试。

    和 run_with_retry 的区别：工具失败有两种形态 ——
      1. 抛异常（参数校验失败、SDK 内部错误）
      2. 返回 {"error": "..."}（工具自己吞掉了异常）
    两种都要处理，所以这里额外用 retry_if_result 判返回值。

    注意：openai SDK 自带 2 次重试（max_retries 默认值），
    但工具层用的是 httpx 直连，不受影响。
    """
    max_retries = _max_retries(max_retries)

    report = RetryReport()

    async def _call() -> Any:
        return await tool.ainvoke(args)

    def _handle_retry(state: RetryCallState) -> None:
        """重试前的钩子：记录次数并通知调用方。

        before_sleep 每次「即将发生一次重试」时调用一次，
        重试耗尽时不会再调它 —— 数它的调用次数就是实际重试次数。
        """
        report.retries += 1
        if on_retry is not None:
            on_retry(state)

    from tenacity import stop_after_attempt

    def _exhausted(retry_state: RetryCallState) -> Any:
        """重试耗尽时的回调。

        必须用 retry_error_callback 而不是让 tenacity 抛 RetryError：
        工具失败通常返回 {"error": "timeout"} 这种字典，
        抛异常会把真正的错误码丢掉（RetryError 里只是包了个 Future）。

        这里把最后一次的结果原样返回，调用方照常能读到 error 字段。
        """
        outcome = retry_state.outcome
        if outcome is None:
            return None
        if outcome.failed:
            # 异常型失败：抛出去，走下面的 except 分支
            raise outcome.exception()  # type: ignore[misc]
        return outcome.result()

    if wait is None:
        wait = wait_exponential(multiplier=WAIT_MULTIPLIER, max=WAIT_MAX)

    retrying = AsyncRetrying(
        stop=stop_after_attempt(max_retries + 1),
        wait=wait,
        # 异常和返回值都要判：两个条件是「或」的关系
        retry=retry_if_exception(is_transient) | retry_if_result(is_transient_tool_result),
        reraise=True,
        retry_error_callback=_exhausted,
        before_sleep=_handle_retry,
    )

    try:
        result = await retrying(_call)
    except BaseException as exc:  # noqa: BLE001
        return RetryOutcome(result=None, error=exc, report=report)

    return RetryOutcome(result=result, error=None, report=report)


__all__ = [
    "RetryOutcome",
    "RetryReport",
    "is_transient",
    "is_transient_tool_result",
    "run_tool_with_retry",
    "run_with_retry",
]
