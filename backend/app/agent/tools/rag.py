"""文档检索工具 —— 接入外部 RAG 服务。

对应 PLAN.md §7 的工具契约：
  成功 -> {"results": [{source, page, text, similarity, ...}], "count": N, "sources": [...]}
  失败 -> {"error": "rag_unavailable" | "rag_timeout" | "rag_error" | "empty_query"}

设计要点：

1. **只取 chunk，不调 LLM。**
   RAG 服务自己的 /api/chat 是「检索 + 生成答案」打包的，
   但本 Agent 会自己调 LLM 汇总 —— 走那条路等于跑两次 LLM
   （成本翻倍、延迟叠加），而且拿到的已是二手答案，没法溯源。
   所以用 RAG 的 /api/search 纯检索端点。

2. **失败也返回字典，不抛异常。**
   和另外两个工具保持一致：工具失败不能让整个链路崩掉，
   要让 LLM 读到「搜不了」然后改用别的方案。

3. **可重试性由 M5 的重试层判断。**
   这里只负责把网络错误翻译成明确的错误码，
   哪些码算 transient 由 retry.is_transient_tool_result 决定。
"""

import httpx
from langchain_core.tools import tool

from app.config import get_settings

#: 单次请求超时时间（秒）。
#: 比 web_search 短 —— 检索是本地向量库，不该等那么久。
TIMEOUT_SECONDS = 30.0

#: 单个 chunk 最多保留多少字符。
#: 超出的部分截断 —— 提示词预算有限，而且完整的原文可以再查一次。
MAX_CHUNK_CHARS = 1500


def _rag_url() -> str | None:
    """返回 RAG 服务的检索地址；没配置则返回 None。"""
    base = get_settings().rag_api_url
    if not base:
        return None
    return f"{base.rstrip('/')}/api/search"


@tool
async def search_docs(query: str, top_k: int = 5, doc_id: str | None = None) -> dict:
    """在内部文档库中检索相关内容。

    只返回原文片段（chunk），不生成答案 —— 回答由你自己组织。

    Args:
        query: 检索关键词。用文档里可能出现的术语，不要用口语化提问。
        top_k: 返回片段数量，默认 5，最多 10。
        doc_id: 可选，限定只检索某个文档（知道文档 ID 时用）。
    """
    query = (query or "").strip()
    if not query:
        return {"error": "empty_query"}

    url = _rag_url()
    if not url:
        return {"error": "rag_not_configured"}

    # 限制条数范围，防止模型传个 1000
    # 注意不能用 `top_k or 5` —— 那样 top_k=0 会被当成"没传"，
    # 结果变成 5 而不是钳到下限 1。
    try:
        top_k = int(top_k)
    except (TypeError, ValueError):
        top_k = 5
    top_k = max(1, min(top_k, 10))

    payload: dict = {"query": query, "top_k": top_k}
    if doc_id:
        payload["doc_id"] = doc_id

    try:
        async with httpx.AsyncClient(timeout=TIMEOUT_SECONDS) as client:
            resp = await client.post(url, json=payload)
    except httpx.TimeoutException:
        return {"error": "rag_timeout"}
    except httpx.HTTPError:
        return {"error": "rag_unavailable"}

    if resp.status_code != 200:
        # RAG 服务的错误结构是 {code, message, detail}
        try:
            detail = resp.json()
            code = detail.get("code", "rag_error")
            message = detail.get("message", "")
        except ValueError:
            code = "rag_error"
            message = resp.text[:200]
        return {"error": code, "message": message}

    try:
        data = resp.json()
    except ValueError:
        return {"error": "rag_error", "message": "响应不是合法 JSON"}

    results = data.get("results") or []

    # 裁剪成 agent 需要的结构，顺便限制 text 长度 ——
    # 一个 chunk 可能上千字，全塞进提示词会挤爆上下文。
    trimmed = []
    for item in results[:top_k]:
        text = item.get("text", "")
        trimmed.append(
            {
                "source": item.get("source", ""),
                "page": item.get("page", 1),
                "text": text[:MAX_CHUNK_CHARS],
                "similarity": round(float(item.get("similarity", 0)), 3),
                "doc_id": item.get("doc_id", ""),
            }
        )

    return {
        "results": trimmed,
        "count": len(trimmed),
        "sources": data.get("sources") or [],
    }
