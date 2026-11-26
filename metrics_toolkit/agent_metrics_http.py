# -*- coding: utf-8 -*-
"""
agent_metrics_http.py — 通过 SSE 事件流统计 Agent 链路指标（零业务代码改动）
=============================================================================
原理：你的 /api/chat 已经把图中的轨迹推成 SSE 事件：
  tool_result   每个工具执行回执 {name, ok, latency_ms, retry, ...}
  retry         每次自动重试       {layer, stage, attempt, ...}
  message_end   结束状态           {finish_reason: stop|error}
  content_delta 最终答案文本片段

所以本脚本只是"外部观察者"：发请求 → 收 SSE → 数事件 → 出指标。
面试追问"数字怎么来的"：答「外部抓 SSE 事件流统计，口径可复现，没改业务代码」。

依赖：仅 Python 标准库（urllib），无需 pip install。
用法：
    python agent_metrics_http.py            # 跑全部任务
    python agent_metrics_http.py --n 3      # 先跑 3 条冒烟测试
"""
import argparse
import json
import pathlib
import statistics
import time
import urllib.request
import uuid

HERE = pathlib.Path(__file__).parent
TASKS = HERE / "tasks.jsonl"
AGENT_URL = "http://127.0.0.1:8000/api/chat"   # 你的后端地址（README: 8000）
REQUEST_TIMEOUT = 180                          # 单任务最长等待（复合任务+LLM 生成）


def run_task(task_text: str) -> dict:
    """发一条任务给 Agent，抓完整 SSE 流，返回统计结构。"""
    body = json.dumps({
        "message": task_text,
        "thread_id": f"eval-{uuid.uuid4().hex[:12]}",  # 每条任务独立会话，避免记忆串味
        "temperature": 0.2,                            # 降低生成随机性，数字更可复现
    }).encode("utf-8")
    req = urllib.request.Request(
        AGENT_URL, data=body,
        headers={"Content-Type": "application/json", "Accept": "text/event-stream"},
    )

    tool_calls, retries = [], 0
    answer_parts, finish_reason, event_name = [], None, None
    plan_steps = 0

    with urllib.request.urlopen(req, timeout=REQUEST_TIMEOUT) as resp:
        for raw in resp:
            line = raw.decode("utf-8", errors="replace").rstrip("\r\n")
            if line == "":                      # 空行 = 一条 SSE 事件结束
                if event_name == "message_end":
                    finish_reason = getattr(run_task, "_last_data", {}).get("finish_reason")
                event_name, data_buf = None, ""
                continue
            if line.startswith("event:"):
                event_name = line[6:].strip()
                run_task._last_data = {}
            elif line.startswith("data:"):
                try:
                    data = json.loads(line[5:].strip())
                except json.JSONDecodeError:
                    continue
                run_task._last_data = data
                if event_name == "tool_result":
                    tool_calls.append({
                        "name": data.get("name", "unknown"),
                        "latency_ms": data.get("latency_ms", 0),
                        "ok": bool(data.get("ok")),
                        "retry": data.get("retry", 0),
                    })
                elif event_name == "retry":
                    retries += 1
                elif event_name == "content_delta":
                    answer_parts.append(data.get("delta", ""))
                elif event_name == "plan_update" or event_name == "plan":
                    steps = data.get("steps") or data.get("plan") or []
                    plan_steps = len(steps)
                elif event_name == "message_end":
                    finish_reason = data.get("finish_reason")

    answer = "".join(answer_parts)
    return {
        "answer": answer,
        "rounds": len(tool_calls),      # 工具调用轮数 = tool_result 事件数
        "retries": retries,             # 自动重试次数 = retry 事件数（含工具层+LLM层）
        "tool_calls": tool_calls,
        "plan_steps": plan_steps,
        "success": finish_reason == "stop" and bool(answer.strip()),
        "finish_reason": finish_reason,
    }


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--n", type=int, default=0, help="只跑前 N 条（冒烟测试用）")
    args = ap.parse_args()

    tasks = [json.loads(l) for l in TASKS.read_text(encoding="utf-8").splitlines()
             if l.strip() and not l.strip().startswith("#")]
    if args.n:
        tasks = tasks[:args.n]
    if not tasks:
        raise SystemExit(f"{TASKS} 为空，先写测试任务")

    wall_times, rounds, retries, plan_steps = [], [], [], []
    per_tool, ok_tasks = {}, 0
    for i, row in enumerate(tasks, 1):
        t0 = time.perf_counter()
        try:
            out = run_task(row["task"])
        except Exception as exc:
            print(f"[{i}/{len(tasks)}] FAILED: {row['task'][:28]}... -> {type(exc).__name__}: {exc}")
            out = {"rounds": 0, "retries": 0, "tool_calls": [], "plan_steps": 0, "success": False}
        dt = time.perf_counter() - t0
        wall_times.append(dt)
        rounds.append(out["rounds"])
        retries.append(out["retries"])
        plan_steps.append(out.get("plan_steps", 0))
        ok_tasks += int(out["success"])
        for c in out["tool_calls"]:
            s = per_tool.setdefault(c["name"], {"n": 0, "ms": [], "fail": 0, "retry": 0})
            s["n"] += 1
            s["ms"].append(c["latency_ms"])
            s["fail"] += int(not c["ok"])
            s["retry"] += c.get("retry", 0)
        print(f"[{i}/{len(tasks)}] ok={out['success']} 步数={out.get('plan_steps')} "
              f"轮数={out['rounds']} 重试={out['retries']} {dt:.2f}s  {row['task'][:24]}...")

    n = max(len(tasks), 1)
    print("\n" + "=" * 58)
    print(f"任务数: {len(tasks)}   成功: {ok_tasks}   成功率: {ok_tasks / n * 100:.1f}%")
    print(f"平均规划步数: {statistics.mean(plan_steps):.2f}")
    print(f"平均工具调用轮数: {statistics.mean(rounds):.2f}")
    print(f"平均端到端耗时: {statistics.mean(wall_times):.2f}s   最大: {max(wall_times):.2f}s")
    print(f"重试事件总数: {sum(retries)}（工具层+LLM 层）")
    print("分工具统计：")
    for name, s in per_tool.items():
        print(f"  {name}: 调用 {s['n']} 次, 平均 {statistics.mean(s['ms']):.0f}ms, "
              f"失败 {s['fail']} 次, 重试 {s['retry']} 次")


if __name__ == "__main__":
    main()
