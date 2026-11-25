"""GET /api/models —— 列出可用的模型和 provider。

前端用它来渲染模型切换器：
  - 哪些 provider 配好了 key（没配的置灰，不让选）
  - 每个 provider 下有哪些模型
  - 当前默认是哪个

为什么要后端提供而不是前端硬编码：
模型名和「配没配 key」是后端状态 —— 前端不知道 .env 里有什么。
硬编码一份列表在设置页和后端配置就容易对不上
（之前就踩过：设置页列了 gpt-4o，但 base_url 指向 MiniMax，选了必报错）。
"""

from fastapi import APIRouter

from app.agent.providers import list_providers
from app.config import get_settings

router = APIRouter(prefix="/api", tags=["models"])


@router.get("/models")
async def list_models() -> dict:
    """返回所有 provider 及其模型列表。"""
    settings = get_settings()
    providers = list_providers(settings)

    return {
        "default_model": settings.openai_model,
        "providers": [
            {
                "id": p.id,
                "label": p.label,
                # 没配 key 的 provider 不给选
                "configured": p.configured,
                "default_model": p.default_model,
                "models": list(p.models),
            }
            for p in providers
        ],
    }
