"""RAG 检索工具测试（search_docs）。

核心要验证：
  1. 成功时返回约定结构（results / count / sources）
  2. 失败时返回错误字典而不是抛异常
  3. 错误码的语义和 M5 重试层对得上（transient vs permanent）
  4. 没配 RAG 地址时明确报错，而不是静默失败
"""

import asyncio

import httpx
import pytest

from app.agent.retry import is_transient_tool_result
from app.agent.tools.rag import search_docs


# ---------------------------------------------------------------------------
# 测试替身
# ---------------------------------------------------------------------------

class _FakeResponse:
    """模拟 httpx.Response 的最小接口。"""

    def __init__(self, status_code: int, payload=None, text: str = "") -> None:
        self.status_code = status_code
        self._payload = payload
        self.text = text or ""

    def json(self):
        if self._payload is None:
            raise ValueError("not json")
        return self._payload


class _FakeClient:
    """替换 httpx.AsyncClient，记录请求内容。"""

    def __init__(self, response=None, exc=None) -> None:
        self.response = response
        self.exc = exc
        self.calls: list[dict] = []

    async def __aenter__(self):
        return self

    async def __aexit__(self, *args):
        return False

    async def post(self, url, json=None, **kwargs):
        self.calls.append({"url": url, "json": json})
        if self.exc is not None:
            raise self.exc
        return self.response


def _patch_client(monkeypatch, client: _FakeClient) -> None:
    """把 httpx.AsyncClient 换成假的。"""
    import app.agent.tools.rag as rag_module

    monkeypatch.setattr(
        rag_module.httpx, "AsyncClient", lambda **kwargs: client
    )


def _patch_settings(monkeypatch, url: str) -> None:
    """设置 RAG 地址。"""
    import app.agent.tools.rag as rag_module

    monkeypatch.setattr(
        rag_module,
        "get_settings",
        lambda: type("S", (), {"rag_api_url": url})(),
    )


def _invoke(**kwargs) -> dict:
    return asyncio.run(search_docs.ainvoke(kwargs))


# ---------------------------------------------------------------------------
# 成功路径
# ---------------------------------------------------------------------------

def test_search_docs_success(monkeypatch: pytest.MonkeyPatch) -> None:
    """检索成功：返回 results / count / sources，且字段被裁剪过。"""
    payload = {
        "results": [
            {
                "doc_id": "doc-1",
                "chunk_index": 2,
                "page": 1,
                "source": "prd-rules.md",
                "text": "金额字段使用 Decimal 类型",
                "score": 0.92,
                "similarity": 0.5743,
                "rerank_score": 0.49,
            }
        ],
        "count": 1,
        "sources": ["prd-rules.md"],
    }
    client = _FakeClient(_FakeResponse(200, payload))
    _patch_client(monkeypatch, client)
    _patch_settings(monkeypatch, "http://rag.test")

    result = _invoke(query="金额字段", top_k=3)

    assert result["count"] == 1
    assert result["sources"] == ["prd-rules.md"]
    item = result["results"][0]
    assert item["source"] == "prd-rules.md"
    assert item["text"] == "金额字段使用 Decimal 类型"
    assert item["similarity"] == 0.574
    # 多余字段不该透传给 LLM
    assert "score" not in item
    assert "rerank_score" not in item
    assert "chunk_index" not in item

    # 请求的地址和参数要对
    assert client.calls[0]["url"] == "http://rag.test/api/search"
    assert client.calls[0]["json"] == {"query": "金额字段", "top_k": 3}


def test_search_docs_sends_doc_id_only_when_given(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """没传 doc_id 时请求体里就不该有这个字段。"""
    client = _FakeClient(_FakeResponse(200, {"results": [], "count": 0}))
    _patch_client(monkeypatch, client)
    _patch_settings(monkeypatch, "http://rag.test/")

    _invoke(query="测试")

    assert "doc_id" not in client.calls[0]["json"]


def test_search_docs_clamps_top_k(monkeypatch: pytest.MonkeyPatch) -> None:
    """top_k 被限制在 1~10，防止模型传个 1000。"""
    client = _FakeClient(_FakeResponse(200, {"results": [], "count": 0}))
    _patch_client(monkeypatch, client)
    _patch_settings(monkeypatch, "http://rag.test")

    _invoke(query="测试", top_k=999)
    assert client.calls[0]["json"]["top_k"] == 10

    _invoke(query="测试", top_k=0)
    assert client.calls[1]["json"]["top_k"] == 1


def test_search_docs_truncates_long_chunk(monkeypatch: pytest.MonkeyPatch) -> None:
    """超长的 chunk 会被截断 —— 提示词预算有限。"""
    from app.agent.tools.rag import MAX_CHUNK_CHARS

    payload = {"results": [{"source": "a.md", "text": "x" * 5000}], "count": 1}
    client = _FakeClient(_FakeResponse(200, payload))
    _patch_client(monkeypatch, client)
    _patch_settings(monkeypatch, "http://rag.test")

    result = _invoke(query="测试")
    assert len(result["results"][0]["text"]) == MAX_CHUNK_CHARS


def test_search_docs_respects_top_k_when_trimming(monkeypatch: pytest.MonkeyPatch) -> None:
    """RAG 返回得比请求的多时，按请求的 top_k 裁剪。"""
    payload = {
        "results": [{"source": f"{i}.md", "text": "内容"} for i in range(5)],
        "count": 5,
    }
    client = _FakeClient(_FakeResponse(200, payload))
    _patch_client(monkeypatch, client)
    _patch_settings(monkeypatch, "http://rag.test")

    result = _invoke(query="测试", top_k=2)
    assert result["count"] == 2
    assert len(result["results"]) == 2


# ---------------------------------------------------------------------------
# 失败路径
# ---------------------------------------------------------------------------

def test_search_docs_rejects_empty_query(monkeypatch: pytest.MonkeyPatch) -> None:
    """空查询词直接拒绝，不发请求。"""
    client = _FakeClient(_FakeResponse(200, {"results": []}))
    _patch_client(monkeypatch, client)
    _patch_settings(monkeypatch, "http://rag.test")

    assert _invoke(query="   ") == {"error": "empty_query"}
    assert client.calls == []


def test_search_docs_without_config(monkeypatch: pytest.MonkeyPatch) -> None:
    """没配 RAG 地址时明确报错。"""
    _patch_settings(monkeypatch, "")

    assert _invoke(query="测试") == {"error": "rag_not_configured"}


def test_search_docs_timeout(monkeypatch: pytest.MonkeyPatch) -> None:
    """超时 → rag_timeout（可重试）。"""
    client = _FakeClient(exc=httpx.ReadTimeout("slow"))
    _patch_client(monkeypatch, client)
    _patch_settings(monkeypatch, "http://rag.test")

    result = _invoke(query="测试")
    assert result == {"error": "rag_timeout"}
    assert is_transient_tool_result(result) is True


def test_search_docs_unavailable(monkeypatch: pytest.MonkeyPatch) -> None:
    """连不上 → rag_unavailable（可重试）。"""
    client = _FakeClient(exc=httpx.ConnectError("refused"))
    _patch_client(monkeypatch, client)
    _patch_settings(monkeypatch, "http://rag.test")

    result = _invoke(query="测试")
    assert result == {"error": "rag_unavailable"}
    assert is_transient_tool_result(result) is True


def test_search_docs_upstream_error_body(monkeypatch: pytest.MonkeyPatch) -> None:
    """RAG 返回非 200：把它的错误码带回来。"""
    payload = {"code": "embedding_unavailable", "message": "模型未加载"}
    client = _FakeClient(_FakeResponse(503, payload))
    _patch_client(monkeypatch, client)
    _patch_settings(monkeypatch, "http://rag.test")

    result = _invoke(query="测试")
    assert result["error"] == "embedding_unavailable"
    assert result["message"] == "模型未加载"


def test_search_docs_non_json_error(monkeypatch: pytest.MonkeyPatch) -> None:
    """上游返回的不是 JSON 也不能抛异常。"""
    client = _FakeClient(_FakeResponse(500, None, text="<html>boom</html>"))
    _patch_client(monkeypatch, client)
    _patch_settings(monkeypatch, "http://rag.test")

    result = _invoke(query="测试")
    assert result["error"] == "rag_error"
    assert "boom" in result["message"]


def test_search_docs_invalid_json_success(monkeypatch: pytest.MonkeyPatch) -> None:
    """200 但响应体不是合法 JSON。"""
    client = _FakeClient(_FakeResponse(200, None, text="not json"))
    _patch_client(monkeypatch, client)
    _patch_settings(monkeypatch, "http://rag.test")

    result = _invoke(query="测试")
    assert result == {"error": "rag_error", "message": "响应不是合法 JSON"}


# ---------------------------------------------------------------------------
# 与 M5 重试层的契约
# ---------------------------------------------------------------------------

@pytest.mark.parametrize(
    "error",
    ["rag_not_configured", "empty_query", "embedding_unavailable"],
)
def test_non_transient_rag_errors_not_retried(error: str) -> None:
    """这些错误重试也没用，不应该被重试层反复尝试。"""
    assert is_transient_tool_result({"error": error}) is False
