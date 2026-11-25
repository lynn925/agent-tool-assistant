"""M6 多 provider 支持 —— 模型名 → (base_url, api_key) 的解析。

背景：不同厂商的模型走不同的接口地址和 key。
之前只有一个全局的 OPENAI_BASE_URL / OPENAI_API_KEY，
所以在前端切模型名没用 —— 换个模型名的同时 base_url 还是老的，
上游就会报 "unknown model"。

现在按模型名前缀路由到对应的 provider：

    MiniMax-*  → OPENAI_BASE_URL + OPENAI_API_KEY
    deepseek-* → DEEPSEEK_BASE_URL + DEEPSEEK_API_KEY
    其它        → 当作 OpenAI 官方模型（base_url 为空）

DeepSeek 也是 OpenAI 兼容格式，所以只是换了 base_url 和 key。
"""

from __future__ import annotations

from dataclasses import dataclass

from app.config import Settings, get_settings


@dataclass(frozen=True)
class Provider:
    """一个模型服务商。"""

    #: 标识符，前端用它分组显示
    id: str
    #: 显示名
    label: str
    #: OpenAI 兼容接口地址；None 表示用官方地址
    base_url: str | None
    #: API key
    api_key: str
    #: 这个 provider 下的模型列表
    models: tuple[str, ...]
    #: 默认模型
    default_model: str

    @property
    def configured(self) -> bool:
        """有没有配 key —— 没配就不能用。"""
        return bool(self.api_key)


def _minimax_models() -> tuple[str, ...]:
    """MiniMax 的模型列表。

    这是一个"推荐列表"，不是接口返回的真实列表 ——
    真实列表要调 /models 才能拿到，那样每次都要联网。
    用户也可以在设置页手填别的模型名。
    """
    return (
        "MiniMax-M3",
        "MiniMax-M3.1-Flash",
        "MiniMax-M2.7",
        "MiniMax-M2.7-highspeed",
    )


def _deepseek_models() -> tuple[str, ...]:
    """DeepSeek 的模型列表。"""
    return (
        "deepseek-v4-pro",
        "deepseek-v4-flash",
        "deepseek-chat",
        "deepseek-reasoner",
    )


def list_providers(settings: Settings | None = None) -> list[Provider]:
    """列出所有 provider，标记哪些配好了 key。"""
    s = settings or get_settings()

    return [
        Provider(
            id="minimax",
            label="MiniMax",
            base_url=s.openai_base_url or None,
            api_key=s.openai_api_key,
            models=_minimax_models(),
            default_model=s.openai_model,
        ),
        Provider(
            id="deepseek",
            label="DeepSeek",
            base_url=s.deepseek_base_url or None,
            api_key=s.deepseek_api_key,
            models=_deepseek_models(),
            default_model=s.deepseek_model,
        ),
    ]


def resolve_provider(
    model: str | None,
    settings: Settings | None = None,
) -> Provider:
    """根据模型名找出该用哪个 provider。

    路由规则：
      1. 模型名以 "deepseek" 开头 → DeepSeek
      2. 模型名以 "MiniMax"（忽略大小写）开头 → MiniMax
      3. 其它 → MiniMax（作为兜底，因为它现在是默认 provider）

    没有指定模型时，返回**当前默认**的 provider（带 key 的那个优先）。
    """
    s = settings or get_settings()
    providers = list_providers(s)

    if model:
        lowered = model.lower()
        if lowered.startswith("deepseek"):
            return _by_id(providers, "deepseek")
        if lowered.startswith("minimax"):
            return _by_id(providers, "minimax")

    # 没指定模型：用默认模型所在的 provider
    default_model = s.openai_model
    if default_model.lower().startswith("deepseek"):
        return _by_id(providers, "deepseek")

    return _by_id(providers, "minimax")


def _by_id(providers: list[Provider], provider_id: str) -> Provider:
    """按 id 找 provider。"""
    for p in providers:
        if p.id == provider_id:
            return p
    raise KeyError(f"未知的 provider: {provider_id}")


def provider_for_model(
    model: str | None,
    settings: Settings | None = None,
) -> tuple[str, str | None, str]:
    """返回 (模型名, base_url, api_key)。

    这是 nodes._model() 真正要的东西。

    如果模型属于某个 provider 但那个 provider 没配 key，
    抛 ProviderNotConfigured —— 让上层给出清晰的提示，
    而不是让上游报一个含糊的 401。
    """
    s = settings or get_settings()
    provider = resolve_provider(model, s)

    # 没配 key 就明确报错
    if not provider.configured:
        raise ProviderNotConfigured(provider)

    # 模型名：用户指定了就用指定的，否则用 provider 的默认模型
    model_name = model or provider.default_model

    return model_name, provider.base_url, provider.api_key


class ProviderNotConfigured(Exception):
    """选了某个 provider 但它没配 key。"""

    def __init__(self, provider: Provider) -> None:
        self.provider = provider
        super().__init__(
            f"{provider.label} 还没配置 API Key。"
            f"请在 backend/.env 里设置对应的环境变量"
            f"（{provider.id.upper()}_API_KEY）后重启后端。"
        )


__all__ = [
    "Provider",
    "ProviderNotConfigured",
    "list_providers",
    "provider_for_model",
    "resolve_provider",
]
