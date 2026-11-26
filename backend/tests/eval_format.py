"""回答格式评测 —— 看 aggregator 输出的文本长什么样。

用法：
    cd backend && source .venv/bin/activate && python tests/eval_format.py

用途：回答格式出问题（比如 Markdown 没渲染、LaTeX 裸奔、千分位不一致）时，
先跑这个脚本看后端吐出的**原始文本**长什么样 —— 区分是模型的问题还是前端渲染的问题。
"""

import json
import sys
import urllib.request

QUERIES = [
    "帮我算一下 (123 + 456) * 789",
    "1+1等于多少",
    "帮我算一下 2^10",
    "计算一下 sqrt(2) 是多少",
    "帮我算一下 1/3",
    "帮我算一下 (123 + 456) * 789，再除以 7",
]


def ask(question: str) -> str:
    payload = json.dumps(
        {"message": question, "thread_id": f"eval-{abs(hash(question))}"},
        ensure_ascii=False,
    ).encode()
    req = urllib.request.Request(
        "http://localhost:8000/api/chat",
        data=payload,
        headers={"Content-Type": "application/json"},
    )
    out: list[str] = []
    with urllib.request.urlopen(req, timeout=180) as resp:
        for raw in resp:
            line = raw.decode("utf-8").strip()
            if not line.startswith("data: "):
                continue
            try:
                event = json.loads(line[6:])
            except json.JSONDecodeError:
                continue
            if "delta" in event:
                out.append(event["delta"])
    return "".join(out)


def main() -> None:
    for q in QUERIES:
        try:
            answer = ask(q)
        except Exception as exc:  # noqa: BLE001
            print(f"[ERROR] {q} -> {exc}")
            continue
        print(f"=== {q}")
        print(repr(answer))
        print()


if __name__ == "__main__":
    sys.exit(main())
