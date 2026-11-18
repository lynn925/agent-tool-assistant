"""M2 SSE endpoint tests (PLAN.md §4 event protocol)."""

import json

import pytest
from fastapi.testclient import TestClient

from app.api.chat import _ThinkFilter
from app.main import app

client = TestClient(app)


def _parse_sse(payload: str) -> list[tuple[str, dict]]:
    events: list[tuple[str, dict]] = []
    for frame in payload.strip().split("\n\n"):
        name = None
        data: list[str] = []
        for line in frame.splitlines():
            if line.startswith("event:"):
                name = line[len("event:") :].strip()
            elif line.startswith("data:"):
                data.append(line[len("data:") :].strip())
        if name and data:
            events.append((name, json.loads("\n".join(data))))
    return events


def test_chat_requires_api_key(monkeypatch: pytest.MonkeyPatch) -> None:
    from app.config import get_settings

    monkeypatch.setattr(get_settings(), "openai_api_key", "", raising=False)
    r = client.post("/api/chat", json={"message": "hi"})
    assert r.status_code == 503


@pytest.mark.parametrize(
    ("chunks", "expected"),
    [
        (["<think>reasoning</think>hello"], "hello"),
        (["plain text"], "plain text"),
        (["a<think>b", "c</think>d"], "ad"),
        (["split tag: <thi", "nk>x</think>y"], "split tag: y"),
    ],
)
def test_think_filter(chunks: list[str], expected: str) -> None:
    filt = _ThinkFilter()
    out = "".join(filt.feed(c) for c in chunks) + filt.flush()
    assert out == expected


def test_think_filter_drops_unclosed_tail() -> None:
    filt = _ThinkFilter()
    assert filt.feed("visible<think>hidden") == "visible"
    assert filt.flush() == ""
