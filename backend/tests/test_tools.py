"""M2 工具契约测试（对应 PLAN.md §3）。

重点验证三件事：
  1. 正常输入返回约定的结果结构；
  2. 危险输入被正确拦截，返回对应的错误码；
  3. 失败时是返回错误字典，而不是抛异常。
"""

import asyncio

import pytest

from app.agent.tools.calculator import calculate
from app.agent.tools.search import web_search
from app.agent.tools.weather import get_weather


# ---------------------------------------------------------------------------
# 计算器
# ---------------------------------------------------------------------------

@pytest.mark.parametrize(
    ("expression", "expected"),
    [
        ("2+2*3", "8"),  # 乘法优先，结果是整数 8
        ("10/4", "2.5"),  # 小数结果
        ("sin(pi/2)", "1"),  # 三角函数（用到白名单里的符号）
    ],
)
def test_calculator_success(expression: str, expected: str) -> None:
    """正常表达式：返回 result 和 latex 两个字段。"""
    result = calculate.invoke({"expression": expression})
    assert "error" not in result
    assert result["result"] == expected
    assert "latex" in result


@pytest.mark.parametrize(
    ("expression", "error"),
    [
        ("import os", "forbidden_keyword"),  # 黑名单：import
        ("__import__('os')", "forbidden_keyword"),  # 黑名单：双下划线
        ("eval(1+1)", "forbidden_keyword"),  # 黑名单：eval(
        ("open('x')", "forbidden_keyword"),  # 黑名单：open(
        ("1;2", "forbidden_keyword"),  # 黑名单：分号
        ("1\n2", "forbidden_keyword"),  # 黑名单：换行
        ("1/0", "evaluation_error"),  # 除零 → 求值失败
        ("2++", "syntax_error"),  # 语法错误
    ],
)
def test_calculator_errors(expression: str, error: str) -> None:
    """危险或非法输入：返回约定的错误码。"""
    result = calculate.invoke({"expression": expression})
    assert result == {"error": error}


def test_calculator_empty_expression() -> None:
    """空表达式按语法错误处理。"""
    assert calculate.invoke({"expression": "  "}) == {"error": "syntax_error"}


# ---------------------------------------------------------------------------
# 联网搜索
# ---------------------------------------------------------------------------

def test_search_without_api_key(monkeypatch: pytest.MonkeyPatch) -> None:
    """缺 SerpAPI key 时返回错误字典，而不是抛异常。

    这样 LangGraph 的链路不会断，LLM 能读到"搜不了"并改用其他方案。
    """
    from app.agent.tools import search as search_module

    monkeypatch.setattr(
        search_module,
        "get_settings",
        lambda: type("S", (), {"serpapi_api_key": ""})(),
    )
    result = asyncio.run(web_search.ainvoke({"query": "LangGraph 教程", "num": 2}))
    assert result == {"error": "serpapi_key_missing"}


def test_search_rejects_empty_query() -> None:
    """空关键词直接拒绝。"""
    result = asyncio.run(web_search.ainvoke({"query": "  "}))
    assert result == {"error": "empty_query"}


# ---------------------------------------------------------------------------
# 天气
# ---------------------------------------------------------------------------

def test_weather_rejects_empty_city() -> None:
    """空城市名按"城市找不到"处理。"""
    result = asyncio.run(get_weather.ainvoke({"city": ""}))
    assert result == {"error": "city_not_found"}
