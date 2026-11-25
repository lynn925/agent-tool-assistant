"""M6 设置项贯通测试。

验证三件事：
  1. 请求级覆盖真的生效（模型/温度/重试次数）
  2. 不传覆盖时回退到全局默认值（向后兼容）
  3. 覆盖是请求级的 —— 不会污染全局配置
"""

import pytest
from fastapi.testclient import TestClient
from pydantic import ValidationError

from app.agent.retry import _max_retries
from app.api.chat import ChatRequest
from app.main import app

client = TestClient(app)


# ---------------------------------------------------------------------------
# 请求模型校验
# ---------------------------------------------------------------------------

def test_settings_are_optional() -> None:
    """不传设置也能用 —— 老的客户端不受影响。"""
    req = ChatRequest(message="hi", thread_id="t1")
    assert req.model is None
    assert req.temperature is None
    assert req.retry_max_attempts is None


def test_settings_accept_valid_values() -> None:
    """合法的设置值要被接受。"""
    req = ChatRequest(
        message="hi",
        thread_id="t1",
        model="gpt-4o-mini",
        temperature=0.5,
        retry_max_attempts=2,
    )
    assert req.model == "gpt-4o-mini"
    assert req.temperature == 0.5
    assert req.retry_max_attempts == 2


@pytest.mark.parametrize(
    ("field", "value"),
    [
        ("temperature", 1.5),  # 超出 0~1
        ("temperature", -0.1),
        ("retry_max_attempts", -1),
        ("retry_max_attempts", 99),  # 上限 5
    ],
)
def test_settings_reject_invalid_values(field: str, value: object) -> None:
    """越界的设置值要在入口就被拒掉，不能流到节点里。"""
    with pytest.raises(ValidationError):
        ChatRequest(message="hi", thread_id="t1", **{field: value})


def test_chat_api_rejects_out_of_range_settings() -> None:
    """API 层同样要拦下越界值（返回 422 而不是 500）。"""
    r = client.post(
        "/api/chat",
        json={
            "message": "hi",
            "thread_id": "t1",
            "temperature": 5.0,
        },
    )
    assert r.status_code == 422


# ---------------------------------------------------------------------------
# 重试次数的覆盖优先级
# ---------------------------------------------------------------------------

def test_max_retries_falls_back_to_global(monkeypatch: pytest.MonkeyPatch) -> None:
    """没有请求级覆盖时，用全局配置。"""
    from app.config import get_settings

    monkeypatch.setattr(get_settings(), "retry_max_attempts", 7, raising=False)
    # 不在图里跑，get_config() 会抛异常 → 走全局配置
    assert _max_retries() == 7


def test_max_retries_uses_explicit_value() -> None:
    """显式传入的值优先于全局配置。"""
    assert _max_retries(2) == 2


def test_max_retries_override_from_config(monkeypatch: pytest.MonkeyPatch) -> None:
    """请求级覆盖（configurable 里的值）优先于全局配置。"""
    from app.config import get_settings

    monkeypatch.setattr(get_settings(), "retry_max_attempts", 7, raising=False)

    # 模拟在图里跑、configurable 里带了覆盖值
    import app.agent.retry as retry_module

    class FakeConfig(dict):
        pass

    def fake_get_config():
        return FakeConfig({"configurable": {"retry_max_attempts": 2}})

    monkeypatch.setattr(retry_module, "get_settings", lambda: get_settings())
    import langgraph.config as lg_config

    monkeypatch.setattr(lg_config, "get_config", fake_get_config)

    # retry.py 是在函数内部 import get_config 的，所以要 patch 模块属性
    assert _max_retries() == 2


# ---------------------------------------------------------------------------
# 覆盖不会污染全局
# ---------------------------------------------------------------------------

def test_override_does_not_mutate_global_settings() -> None:
    """构造带覆盖的请求后，全局配置要原封不动。"""
    from app.config import get_settings

    settings = get_settings()
    before_model = settings.openai_model
    before_retry = settings.retry_max_attempts

    ChatRequest(
        message="hi",
        thread_id="t1",
        model="some-other-model",
        retry_max_attempts=0,
    )

    assert settings.openai_model == before_model
    assert settings.retry_max_attempts == before_retry
