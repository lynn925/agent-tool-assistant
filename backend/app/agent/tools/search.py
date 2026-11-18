"""Web search tool — SerpAPI.

Contract (PLAN.md §3.2):
  success -> [{title, snippet, url}]
  failure -> {error: "serpapi_key_missing"} (never raises)
"""

from langchain_core.tools import tool

from app.config import get_settings

TIMEOUT_SECONDS = 15.0


@tool
async def web_search(query: str, num: int = 5) -> list[dict] | dict:
    """Search the web and return the top results.

    Args:
        query: Search query string.
        num: Number of results to return, 1-10.
    """
    query = (query or "").strip()
    if not query:
        return {"error": "empty_query"}

    num = max(1, min(int(num or 5), 10))

    api_key = get_settings().serpapi_api_key
    if not api_key:
        return {"error": "serpapi_key_missing"}

    import serpapi

    try:
        serp = serpapi.Client(api_key=api_key, timeout=TIMEOUT_SECONDS)
        response = serp.search(q=query, num=num)
    except Exception:
        return {"error": "upstream_error"}

    if not isinstance(response, dict):
        return {"error": "upstream_error"}
    if "error" in response:
        return {"error": "serpapi_error"}

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
