"""M2 SSE 接口测试（对应 PLAN.md §4 事件协议）。

这里不测真实的 LLM 调用（需要网络和 API key），
只测不依赖外部服务的部分：配置校验和推理块过滤器。
"""

import json

import pytest
from fastapi.testclient import TestClient

from app.agent.text import ThinkFilter
from app.main import app

client = TestClient(app)


def _parse_sse(payload: str) -> list[tuple[str, dict]]:
    """把 SSE 响应文本解析成 [(事件名, 数据)] 列表。

    仅用于测试断言，方便检查事件顺序。
    """
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
    """没配 API key 时直接返回 503，不进入流式处理。"""
    from app.config import get_settings

    monkeypatch.setattr(get_settings(), "openai_api_key", "", raising=False)
    r = client.post("/api/chat", json={"message": "hi"})
    assert r.status_code == 503


@pytest.mark.parametrize(
    ("chunks", "expected"),
    [
        # 完整推理块被整段剥掉
        (["<think>reasoning</think>hello"], "hello"),
        # 没有推理块，原样输出
        (["plain text"], "plain text"),
        # 推理块跨 chunk：开始标签在第一个块，结束标签在第二个块
        (["a<think>b", "c</think>d"], "ad"),
        # 标签本身被切断：<thi + nk>
        (["split tag: <thi", "nk>x</think>y"], "split tag: y"),
    ],
)
def test_think_filter(chunks: list[str], expected: str) -> None:
    """推理块过滤器：验证跨 chunk 的标签也能正确剥离。"""
    filt = ThinkFilter()
    out = "".join(filt.feed(c) for c in chunks) + filt.flush()
    assert out == expected


def test_think_filter_drops_unclosed_tail() -> None:
    """没有闭合标签的推理块，内容要被丢弃且不吐尾巴。"""
    filt = ThinkFilter()
    assert filt.feed("visible<think>hidden") == "visible"
    assert filt.flush() == ""
