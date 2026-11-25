"""M3 的三个节点：planner（规划）/ executor（执行）/ aggregator（汇总）。

图结构：
    START → planner → executor → (还有下一步吗？)
                              ├── 有 → executor
                              └── 无 → aggregator → END

设计决策（已与用户确认）：
  1. executor 直接按计划调用工具函数，不再让模型自己选工具 —— 快、省 token、行为确定；
  2. 某步失败时标记为 failed，继续下一步，不阻塞整个计划。

M5 的变化：工具调用和 LLM 调用都套上了重试层（app/agent/retry.py），
失败时通过 SSE 实时告诉前端「第几次重试」。
"""

import asyncio
import json
import re
import time
from typing import Any

from langchain_core.messages import AIMessage, HumanMessage
from langchain_openai import ChatOpenAI
from langgraph.config import get_stream_writer
from pydantic import ValidationError

from app.agent.prompts import AGGREGATOR_PROMPT, PLANNER_PROMPT
from app.agent.retry import is_transient, run_tool_with_retry, run_with_retry
from app.agent.state import AgentState, TaskStep
from app.agent.text import ThinkFilter, extract_conversation, strip_think
from app.agent.tools import ALL_TOOLS, LATENCY_KEY
from app.config import get_settings

#: 最多生成多少个步骤，防止模型把计划拆得过碎
MAX_STEPS = 5

#: 工具名 → 该工具的参数名（用于修正模型给错字段名的情况）
TOOL_ARG_NAMES: dict[str, list[str]] = {
    "get_weather": ["city"],
    "web_search": ["query", "num"],
    "calculate": ["expression"],
}

#: 常见的错误参数名 → 正确参数名
_ARG_ALIASES: dict[str, str] = {
    "location": "city",
    "place": "city",
    "city_name": "city",
    "keyword": "query",
    "q": "query",
    "search": "query",
    "expr": "expression",
    "formula": "expression",
    "text": "expression",
}


def _model(temperature: float = 0.2) -> ChatOpenAI:
    """创建聊天模型实例（不复用 M2 的缓存，因为温度不同）。

    max_retries=0：openai SDK 自带 2 次重试，M5 用 tenacity 做重试，
    两层叠在一起会变成 2×4 次调用，而且用户看不到 SDK 内部重试了几次。
    关掉 SDK 的重试，让 tenacity 当唯一的重试层 —— 这样
    "重试了几次" 才能如实反馈到前端。
    """
    s = get_settings()
    return ChatOpenAI(
        model=s.openai_model,
        api_key=s.openai_api_key or None,
        base_url=s.openai_base_url or None,
        temperature=temperature,
        max_retries=0,
    )


def _retry_message(retry_state, attempt: int) -> str:
    """生成一句人类可读的重试提示。

    会区分「异常型失败」和「返回值型失败」（工具自己吞掉异常时）。
    """
    outcome = retry_state.outcome
    if outcome is not None and outcome.failed:
        exc = outcome.exception()
        return f"{type(exc).__name__}: {exc}"

    # 结果型失败：工具返回了 {"error": "timeout"} 这类字典
    result = outcome.result() if outcome is not None else None
    if isinstance(result, dict) and "error" in result:
        return str(result["error"])
    return "未知错误"


def _extract_json(text: str) -> dict | None:
    """从模型输出里抠出 JSON。

    模型有时会带上 <think>推理</think> 或 ```json 代码块，
    所以先剥掉推理，再找最外层的 {}。
    """
    # 剥掉推理块
    text = strip_think(text)
    # 剥掉 markdown 代码块围栏
    text = re.sub(r"```(?:json)?\s*|\s*```", "", text)
    # 找最外层的 JSON 对象
    start = text.find("{")
    if start == -1:
        return None
    depth = 0
    for i in range(start, len(text)):
        if text[i] == "{":
            depth += 1
        elif text[i] == "}":
            depth -= 1
            if depth == 0:
                try:
                    return json.loads(text[start : i + 1])
                except json.JSONDecodeError:
                    return None
    return None


def _normalize_args(tool: str, args: dict) -> dict:
    """修正模型给错的参数名。

    实测 planner 会把 get_weather 的 city 写成 location，
    所以这里按工具 schema 校正一下。
    """
    if tool not in TOOL_ARG_NAMES:
        return args

    valid = TOOL_ARG_NAMES[tool]
    normalized = dict(args)

    # 别名映射：location → city 之类
    for alias, correct in _ARG_ALIASES.items():
        if alias in normalized and correct in valid and correct not in normalized:
            normalized[correct] = normalized.pop(alias)

    # 丢掉不认识的参数，保留合法的
    return {k: v for k, v in normalized.items() if k in valid}


def _make_step(
    index: int,
    description: str,
    tool: str | None,
    args: dict,
) -> TaskStep:
    """构造一个 TaskStep。"""
    return TaskStep(
        id=f"step-{index}",
        description=description,
        tool=tool,
        args=args,
        status="pending",
        result=None,
        error=None,
        retry=0,
    )


async def planner_node(state: AgentState) -> dict:
    """规划节点：把用户请求拆成 2~5 个步骤。

    输出：plan（步骤列表）和 current_step=0

    M4 变化：会带上历史对话，让 planner 能理解上下文指代
    （比如"再算一下"要知道在算什么）。

    M5 变化：LLM 调用套上重试层，网络抖动/限流会自动重试，
    重试过程通过 SSE 实时推给前端。
    """
    writer = get_stream_writer()
    user_text, history = extract_conversation(state["messages"])
    user_text = user_text or "请帮我完成这个任务"

    # 消息列表：系统提示 → 历史对话 → 当前问题
    payload_messages = [{"role": "system", "content": PLANNER_PROMPT}]
    payload_messages.extend(history)
    payload_messages.append({"role": "user", "content": user_text})

    async def _invoke():
        return await _model().ainvoke(
            payload_messages,
            response_format={"type": "json_object"},
        )

    def _on_retry(retry_state) -> None:
        """重试前推送事件，让前端显示「正在重试」。"""
        writer(
            {
                "event": "retry",
                "layer": "llm",
                "stage": "planner",
                # attempt_number 在 before_sleep 时就是「即将进行的第几次重试」
                "attempt": retry_state.attempt_number,
                "max_attempts": get_settings().retry_max_attempts + 1,
                "message": _retry_message(retry_state, retry_state.attempt_number),
            }
        )

    outcome = await run_with_retry(_invoke, on_retry=_on_retry)

    if not outcome.ok:
        # LLM 层重试耗尽 —— 抛出去，让 chat.py 统一转成 error 事件
        raise outcome.error  # type: ignore[misc]

    response = outcome.result
    raw = response.content if isinstance(response.content, str) else ""
    payload = _extract_json(raw)
    raw_steps = (payload or {}).get("steps") or []

    plan: list[TaskStep] = []
    for idx, item in enumerate(raw_steps[:MAX_STEPS], start=1):
        if not isinstance(item, dict):
            continue
        description = str(item.get("description") or "").strip()
        tool = item.get("tool")
        tool = tool if isinstance(tool, str) and tool in TOOL_ARG_NAMES else None
        args = item.get("args")
        args = _normalize_args(tool, args) if isinstance(args, dict) else {}
        if not description and not tool:
            continue
        plan.append(_make_step(idx, description or "执行任务", tool, args))

    # 模型没给出可用计划时，退化成单步：直接让模型自己回答
    if not plan:
        plan = [_make_step(1, "直接回答用户问题", None, {})]
        writer({"event": "plan_fallback"})

    writer({"event": "plan", "plan": plan})
    return {"plan": plan, "current_step": 0}


async def executor_node(state: AgentState) -> dict:
    """执行节点：执行当前这一步。

    M5 变化：工具调用套上重试层，transient 失败会指数退避重试（1s/2s/4s）。

    状态语义（已与用户确认）：
      done     成功
      failed   这一步执行了但没成功（工具报错 / 重试耗尽）→ 继续执行后续步骤
      skipped  这一步根本没法执行（工具不存在 / 参数非法）→ 同样继续后续步骤
    """
    writer = get_stream_writer()
    plan = list(state.get("plan") or [])
    index = state.get("current_step", 0)

    if index < 0 or index >= len(plan):
        return {"current_step": len(plan)}

    step = dict(plan[index])
    step["status"] = "running"
    plan[index] = step
    writer({"event": "step", "step": step})

    started = time.perf_counter()
    tool_name = step.get("tool")
    args = step.get("args") or {}

    if not tool_name:
        # 不需要工具的步骤，直接标记完成
        step["status"] = "done"
        step["result"] = None
        plan[index] = step
        writer({"event": "step", "step": step})
        return {"plan": plan, "current_step": index + 1}

    # 按计划调用工具
    tool = next((t for t in ALL_TOOLS if t.name == tool_name), None)
    if tool is None:
        # 工具根本不存在 —— 这步没法执行
        step["status"] = "skipped"
        step["error"] = "unknown_tool"
        plan[index] = step
        writer({"event": "step", "step": step})
        return {"plan": plan, "current_step": index + 1}

    def _on_retry(retry_state) -> None:
        """重试前推送事件，让前端实时显示「正在重试」。"""
        writer(
            {
                "event": "retry",
                "layer": "tool",
                "stage": step["id"],
                "name": tool_name,
                # attempt_number 在 before_sleep 时就是「即将进行的第几次重试」
                "attempt": retry_state.attempt_number,
                "max_attempts": get_settings().retry_max_attempts + 1,
                "message": _retry_message(retry_state, retry_state.attempt_number),
            }
        )

    outcome = await run_tool_with_retry(tool, args, on_retry=_on_retry)
    latency_ms = round((time.perf_counter() - started) * 1000, 1)
    step["retry"] = outcome.report.retries

    if outcome.error is not None:
        # 抛异常了：参数非法（permanent）就跳过，其他算失败
        exc = outcome.error
        is_validation = isinstance(exc, ValidationError)
        step["status"] = "skipped" if is_validation else "failed"
        step["error"] = (
            f"invalid_arguments: {exc}"
            if is_validation
            else f"{type(exc).__name__}: {exc}"
        )
        step["result"] = None
    else:
        result = outcome.result
        # 工具返回里带 "error" 字段就代表失败
        if isinstance(result, dict) and "error" in result:
            step["status"] = "failed"
            step["error"] = str(result["error"])
            step["result"] = None
        else:
            step["status"] = "done"
            # 摘掉内部的耗时字段，它不属于工具的业务结果
            if isinstance(result, dict):
                result = {k: v for k, v in result.items() if k != LATENCY_KEY}
            step["result"] = result

    plan[index] = step
    writer({"event": "step", "step": step})
    writer(
        {
            "event": "tool_result",
            "id": step["id"],
            "name": tool_name,
            "args": args,
            "ok": step["status"] == "done",
            "result": step["result"],
            "error": step["error"],
            "retry": step["retry"],
            "latency_ms": latency_ms,
        }
    )
    return {"plan": plan, "current_step": index + 1}


async def aggregator_node(state: AgentState) -> dict:
    """汇总节点：把各步骤结果综合成最终回答。

    输出：final_answer 和一条 AIMessage 消息。

    这里用 astream 做 token 级推送 —— 模型生成一段就推一段，
    前端能实时看到打字效果。

    M4 变化：会带上历史对话。
    这是记忆能生效的关键 —— 之前只把当前问题给了模型，
    "我叫小明"这类信息传不下去，模型就会说"我不知道你的名字"。

    M5 变化：LLM 调用套上重试层，但**只在还没吐出正文时重试**。
    如果已经推了 token 给前端再重试，前端会收到重复的内容 ——
    所以流已经开始之后的失败直接抛出，不重试。
    """
    writer = get_stream_writer()
    plan = state.get("plan") or []

    # 把步骤结果拼成给汇总器的上下文
    lines = []
    for step in plan:
        desc = step.get("description", "")
        status = step.get("status", "")
        if status == "done":
            lines.append(f"- {desc}：{step.get('result')}")
        elif status in ("failed", "skipped"):
            # M5：failed 和 skipped 都如实告诉汇总器，不要编造结果
            lines.append(f"- {desc}：未完成（{step.get('error')}），已跳过")
        else:
            lines.append(f"- {desc}：{status}")

    # 当前问题 + 历史对话
    user_text, history = extract_conversation(state["messages"])
    user_text = user_text or "请帮我完成这个任务"

    context = "\n".join(lines) if lines else "（没有执行任何步骤）"

    # 消息列表：系统提示 → 历史对话 → 当前问题 + 执行结果
    payload_messages = [{"role": "system", "content": AGGREGATOR_PROMPT}]
    payload_messages.extend(history)
    payload_messages.append(
        {"role": "user", "content": f"用户的问题：{user_text}\n\n执行结果：\n{context}"}
    )

    model = _model()
    think = ThinkFilter()
    answer_parts: list[str] = []
    retries = 0

    async def _stream_once() -> None:
        """跑一遍流式生成，把正文推给前端。"""
        async for chunk in model.astream(payload_messages):
            text = chunk.content if isinstance(chunk.content, str) else ""
            if not text:
                continue
            delta = think.feed(text)
            if delta:
                answer_parts.append(delta)
                writer({"event": "delta", "text": delta})

    while True:
        try:
            await _stream_once()
            break
        except Exception as exc:
            # 已经吐过正文了 —— 重试会导致前端收到重复内容，只能放弃
            if answer_parts:
                raise
            # 永久错误（鉴权失败、请求不合法）不重试
            if not is_transient(exc):
                raise
            # 重试次数用完了
            if retries >= get_settings().retry_max_attempts:
                raise
            retries += 1
            writer(
                {
                    "event": "retry",
                    "layer": "llm",
                    "stage": "aggregator",
                    "attempt": retries,
                    "max_attempts": get_settings().retry_max_attempts + 1,
                    "message": f"{type(exc).__name__}: {exc}",
                }
            )
            # 指数退避：1s / 2s / 4s
            await asyncio.sleep(2 ** (retries - 1))

    # 流结束后补上扣住的尾巴
    trailing = think.flush()
    if trailing:
        answer_parts.append(trailing)
        writer({"event": "delta", "text": trailing})

    answer = "".join(answer_parts).strip()
    return {
        "final_answer": answer,
        "messages": [AIMessage(content=answer)],
    }


def should_continue(state: AgentState) -> str:
    """条件边：还有下一步没执行完就继续，否则去汇总。

    M5：失败（failed）和跳过（skipped）的步骤都不阻塞流程 ——
    它们只是"这一步没拿到结果"，后面的步骤是独立的，照常执行。
    """
    plan = state.get("plan") or []
    current = state.get("current_step", 0)
    if current < len(plan):
        return "executor"
    return "aggregator"
