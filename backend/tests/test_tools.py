"""M2 tool contract tests (PLAN.md §3)."""

import asyncio

import pytest

from app.agent.tools.calculator import calculate
from app.agent.tools.search import web_search
from app.agent.tools.weather import get_weather


@pytest.mark.parametrize(
    ("expression", "expected"),
    [
        ("2+2*3", "8"),
        ("10/4", "2.5"),
        ("sin(pi/2)", "1"),
    ],
)
def test_calculator_success(expression: str, expected: str) -> None:
    result = calculate.invoke({"expression": expression})
    assert "error" not in result
    assert result["result"] == expected
    assert "latex" in result


@pytest.mark.parametrize(
    ("expression", "error"),
    [
        ("import os", "forbidden_keyword"),
        ("__import__('os')", "forbidden_keyword"),
        ("eval(1+1)", "forbidden_keyword"),
        ("open('x')", "forbidden_keyword"),
        ("1;2", "forbidden_keyword"),
        ("1\n2", "forbidden_keyword"),
        ("1/0", "evaluation_error"),
        ("2++", "syntax_error"),
    ],
)
def test_calculator_errors(expression: str, error: str) -> None:
    result = calculate.invoke({"expression": expression})
    assert result == {"error": error}


def test_calculator_empty_expression() -> None:
    assert calculate.invoke({"expression": "  "}) == {"error": "syntax_error"}


def test_search_without_api_key(monkeypatch: pytest.MonkeyPatch) -> None:
    """Missing SerpAPI key must return an error dict, not raise."""
    from app.agent.tools import search as search_module

    monkeypatch.setattr(
        search_module,
        "get_settings",
        lambda: type("S", (), {"serpapi_api_key": ""})(),
    )
    result = asyncio.run(web_search.ainvoke({"query": "LangGraph 教程", "num": 2}))
    assert result == {"error": "serpapi_key_missing"}


def test_search_rejects_empty_query() -> None:
    result = asyncio.run(web_search.ainvoke({"query": "  "}))
    assert result == {"error": "empty_query"}


def test_weather_rejects_empty_city() -> None:
    result = asyncio.run(get_weather.ainvoke({"city": ""}))
    assert result == {"error": "city_not_found"}
