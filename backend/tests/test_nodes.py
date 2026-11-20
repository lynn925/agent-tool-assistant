"""M3 节点逻辑测试（对应 PLAN.md §5）。

这些测试不调真实模型，只验证纯函数和状态转换逻辑：
  - JSON 提取（planner 的输出可能带推理块、markdown 围栏）
  - 参数名归一化（模型可能把 city 写成 location）
  - 步骤状态流转（done / skipped）
"""

import pytest

from app.agent.nodes import _extract_json, _normalize_args, should_continue


# ---------------------------------------------------------------------------
# JSON 提取
# ---------------------------------------------------------------------------

@pytest.mark.parametrize(
    ("raw", "expected"),
    [
        # 标准 JSON
        ('{"steps": []}', {"steps": []}),
        # 带 markdown 代码块围栏
        ('```json\n{"steps": []}\n```', {"steps": []}),
        # 带推理块
        ('<think>let me think</think>{"steps": []}', {"steps": []}),
        # 前后有多余文字
        ('好的，结果如下：{"steps": []} 希望有帮助', {"steps": []}),
    ],
)
def test_extract_json(raw: str, expected: dict) -> None:
    """从各种格式的模型输出里都能抠出 JSON。"""
    assert _extract_json(raw) == expected


def test_extract_json_returns_none_on_garbage() -> None:
    """完全不是 JSON 时返回 None。"""
    assert _extract_json("这不是 JSON") is None
    assert _extract_json("{broken json") is None


# ---------------------------------------------------------------------------
# 参数名归一化
# ---------------------------------------------------------------------------

def test_normalize_args_fixes_location_alias() -> None:
    """模型把 city 写成 location 时要能纠正回来。"""
    assert _normalize_args("get_weather", {"location": "上海"}) == {"city": "上海"}


def test_normalize_args_fixes_other_aliases() -> None:
    """其他常见别名也要能纠正。"""
    assert _normalize_args("web_search", {"keyword": "教程"}) == {"query": "教程"}
    assert _normalize_args("calculate", {"expr": "1+1"}) == {"expression": "1+1"}


def test_normalize_args_drops_unknown_keys() -> None:
    """不认识的参数要被丢掉，避免传给工具时报错。"""
    assert _normalize_args("calculate", {"expression": "1+1", "foo": "bar"}) == {
        "expression": "1+1"
    }


def test_normalize_args_keeps_valid_params() -> None:
    """本来正确的参数不能被改坏。"""
    assert _normalize_args("get_weather", {"city": "上海"}) == {"city": "上海"}


def test_normalize_args_ignores_unknown_tool() -> None:
    """未知工具原样返回。"""
    assert _normalize_args("unknown_tool", {"a": 1}) == {"a": 1}


# ---------------------------------------------------------------------------
# 步骤状态流转
# ---------------------------------------------------------------------------

def _plan(*statuses: str) -> list[dict]:
    """构造一个给定状态的步骤列表。"""
    return [
        {"id": f"step-{i + 1}", "description": "x", "tool": None, "args": {}, "status": s}
        for i, s in enumerate(statuses)
    ]


def test_should_continue_when_steps_remain() -> None:
    """还有步骤没执行完就继续。"""
    assert should_continue({"plan": _plan("done", "pending"), "current_step": 1}) == "executor"


def test_should_continue_to_aggregator_when_done() -> None:
    """全部执行完就去汇总。"""
    assert should_continue({"plan": _plan("done", "done"), "current_step": 2}) == "aggregator"


def test_should_continue_after_failed_step() -> None:
    """失败的步骤不阻塞流程，继续下一步。"""
    assert should_continue({"plan": _plan("skipped", "pending"), "current_step": 1}) == "executor"


def test_should_continue_with_empty_plan() -> None:
    """空计划直接去汇总。"""
    assert should_continue({"plan": [], "current_step": 0}) == "aggregator"
