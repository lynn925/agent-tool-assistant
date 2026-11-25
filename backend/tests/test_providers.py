"""M6 多 provider 测试（模型名 → base_url/api_key 的路由）。

核心要验证：
  1. 模型名能正确路由到对应 provider
  2. 没配 key 时给出明确的错误，而不是含糊的 401
  3. provider 解析是纯函数，不依赖网络
"""

import pytest

from app.agent.providers import (
    ProviderNotConfigured,
    list_providers,
    provider_for_model,
    resolve_provider,
)
from app.config import Settings


def _settings(
    minimax_key: str = "mm-key",
    deepseek_key: str = "",
    openai_model: str = "MiniMax-M3",
) -> Settings:
    """构造一份可控的测试配置。"""
    return Settings(
        openai_api_key=minimax_key,
        openai_model=openai_model,
        openai_base_url="https://api.minimaxi.com/v1",
        deepseek_api_key=deepseek_key,
        deepseek_base_url="https://api.deepseek.com",
        deepseek_model="deepseek-v4-pro",
    )


# ---------------------------------------------------------------------------
# 路由
# ---------------------------------------------------------------------------

@pytest.mark.parametrize(
    ("model", "expected_provider"),
    [
        ("MiniMax-M3", "minimax"),
        ("MiniMax-M2.7-highspeed", "minimax"),
        ("minimax-m3", "minimax"),  # 忽略大小写
        ("deepseek-v4-pro", "deepseek"),
        ("deepseek-chat", "deepseek"),
        ("DeepSeek-Reasoner", "deepseek"),  # 忽略大小写
    ],
)
def test_model_routes_to_provider(
    model: str, expected_provider: str
) -> None:
    """模型名决定用哪个 provider。"""
    provider = resolve_provider(model, _settings())
    assert provider.id == expected_provider


def test_unknown_model_falls_back_to_default_provider() -> None:
    """不认识的模型名走默认 provider（而不是报错）。

    这样用户自己填模型名时，至少会尝试一下 ——
    真的不支持的话由上游报 unknown model，提示更准确。
    """
    provider = resolve_provider("some-unknown-model", _settings())
    assert provider.id == "minimax"


def test_default_model_selects_its_provider() -> None:
    """不指定模型时，用默认模型所在的 provider。"""
    # 默认是 MiniMax
    assert resolve_provider(None, _settings()).id == "minimax"
    # 默认改成 deepseek 就跟着切
    settings = _settings(openai_model="deepseek-v4-pro")
    assert resolve_provider(None, settings).id == "deepseek"


# ---------------------------------------------------------------------------
# base_url / api_key
# ---------------------------------------------------------------------------

def test_deepseek_uses_its_own_base_url_and_key() -> None:
    """选 DeepSeek 模型要用 DeepSeek 的接口地址和 key。"""
    settings = _settings(deepseek_key="ds-key")
    model, base_url, api_key = provider_for_model("deepseek-v4-pro", settings)

    assert model == "deepseek-v4-pro"
    assert base_url == "https://api.deepseek.com"
    assert api_key == "ds-key"


def test_minimax_uses_its_own_base_url_and_key() -> None:
    """选 MiniMax 模型要用 MiniMax 的接口地址和 key。"""
    settings = _settings(minimax_key="mm-key", deepseek_key="ds-key")
    model, base_url, api_key = provider_for_model("MiniMax-M3", settings)

    assert model == "MiniMax-M3"
    assert base_url == "https://api.minimaxi.com/v1"
    assert api_key == "mm-key"


def test_no_model_uses_provider_default() -> None:
    """不指定模型时用 provider 的默认模型名。"""
    model, _, _ = provider_for_model(None, _settings())
    assert model == "MiniMax-M3"


# ---------------------------------------------------------------------------
# 没配 key
# ---------------------------------------------------------------------------

def test_unconfigured_provider_raises_clear_error() -> None:
    """provider 没配 key 时抛明确的异常，而不是让上游报 401。"""
    with pytest.raises(ProviderNotConfigured) as exc_info:
        provider_for_model("deepseek-v4-pro", _settings(deepseek_key=""))

    exc = exc_info.value
    assert exc.provider.id == "deepseek"
    # 错误信息要告诉用户去哪儿填 key
    assert "DEEPSEEK_API_KEY" in str(exc)


def test_configured_provider_does_not_raise() -> None:
    """配了 key 就正常返回。"""
    model, _, api_key = provider_for_model(
        "deepseek-v4-pro", _settings(deepseek_key="ds-key")
    )
    assert model == "deepseek-v4-pro"
    assert api_key == "ds-key"


# ---------------------------------------------------------------------------
# provider 列表
# ---------------------------------------------------------------------------

def test_list_providers_marks_configured_state() -> None:
    """列表要标出哪些 provider 配好了 key。"""
    providers = list_providers(_settings(deepseek_key=""))

    by_id = {p.id: p for p in providers}
    assert by_id["minimax"].configured is True
    assert by_id["deepseek"].configured is False

    # 再配上就是 True
    by_id = {p.id: p for p in list_providers(_settings(deepseek_key="ds-key"))}
    assert by_id["deepseek"].configured is True


def test_providers_expose_model_lists() -> None:
    """每个 provider 要有模型列表，前端才能渲染切换器。"""
    for p in list_providers(_settings()):
        assert len(p.models) > 0
        assert p.default_model in p.models


# ---------------------------------------------------------------------------
# API
# ---------------------------------------------------------------------------

def test_models_endpoint_returns_providers() -> None:
    """/api/models 要返回 provider 列表和配置状态。"""
    from fastapi.testclient import TestClient

    from app.main import app

    client = TestClient(app)
    r = client.get("/api/models")

    assert r.status_code == 200
    data = r.json()
    assert "providers" in data
    assert "default_model" in data

    ids = {p["id"] for p in data["providers"]}
    assert "minimax" in ids
    assert "deepseek" in ids

    for provider in data["providers"]:
        assert "configured" in provider
        assert "models" in provider
