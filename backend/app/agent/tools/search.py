"""联网搜索工具 —— SerpAPI。

对应 PLAN.md §3.2 的契约：
  成功 -> [{title, snippet, url}]
  失败 -> {error: "serpapi_key_missing"}

关键设计：缺 API key 时返回错误字典而不是抛异常。
这样 LangGraph 的 ToolNode 不会整个链路崩掉，
LLM 能读到"搜不了"这条信息，然后改用别的工具或直接告诉用户。
"""

from langchain_core.tools import tool

from app.config import get_settings

#: SerpAPI 请求超时时间（秒）。它比 wttr.in 慢得多，因为是商业接口。
TIMEOUT_SECONDS = 15.0


@tool
async def web_search(query: str, num: int = 5) -> list[dict] | dict:
    """在互联网上搜索，返回若干条结果。

    Args:
        query: 搜索关键词。
        num: 返回结果条数，取值 1~10。
    """
    query = (query or "").strip()
    if not query:
        return {"error": "empty_query"}

    # 限制条数范围，防止模型传个 1000 把额度耗光
    num = max(1, min(int(num or 5), 10))

    # 延迟导入配置，避免模块加载时就要求 key 存在
    api_key = get_settings().serpapi_api_key
    if not api_key:
        return {"error": "serpapi_key_missing"}

    # serpapi 是同步库，放在函数内部导入（只导入一次，Python 会缓存）
    import serpapi

    try:
        serp = serpapi.Client(api_key=api_key, timeout=TIMEOUT_SECONDS)
        response = serp.search(q=query, num=num)
    except Exception:
        # 任何网络/鉴权/额度问题都归为上游错误
        return {"error": "upstream_error"}

    if not isinstance(response, dict):
        return {"error": "upstream_error"}
    if "error" in response:
        # SerpAPI 额度用尽等情况会在响应里带 error 字段
        return {"error": "serpapi_error"}

    # 只取前 num 条，并裁剪成统一的 {title, snippet, url} 结构
    results = []
    for item in response.get("organic_results", [])[:num]:
        if not isinstance(item, dict):
            continue
        results.append(
            {
                "title": item.get("title", ""),
                "snippet": item.get("snippet", ""),
                "url": item.get("link", ""),
            }
        )
    return results
