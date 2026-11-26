# metrics_toolkit — Agent 链路评测

评测脚本与任务集，**不参与应用运行**，只用于可复现地测量 Agent 表现。
面试时被问「简历上的数字怎么来的」，答案就是这里：自建任务集 + 外部抓 SSE 事件流统计。

## 文件

| 文件 | 用途 |
|---|---|
| `agent_metrics_http.py` | 通过 `/api/chat` 的 SSE 事件（`tool_result` / `retry` / `message_end` / `plan_update`）统计：规划步数、工具调用轮数、端到端耗时、重试次数、分工具统计。仅用 Python 标准库，零业务代码改动。 |
| `tasks.jsonl` | 20 条复合任务，覆盖天气 / 搜索 / 计算 / 文档检索四类工具。每条任务用独立 `thread_id`，不受历史记忆干扰。 |

## 跑法

1. 启动后端（`npm run dev`，API 在 `:8000`）；涉及内部文档的任务还需启动 RAG 服务（`:8001`）并配好 `backend/.env` 的 `RAG_API_URL`。
2. 冒烟测试（先跑 3 条，确认 SSE 解析正常）：
   ```bash
   python metrics_toolkit/agent_metrics_http.py --n 3
   ```
3. 全量评测：
   ```bash
   python metrics_toolkit/agent_metrics_http.py
   ```

## 口径说明

- 工具调用轮数 = `tool_result` 事件数；自动重试次数 = `retry` 事件数（含工具层与 LLM 层）。
- 成功率 = `message_end` 为 `stop` 且最终回答非空的比例；任务失败原因会逐条打印。
- 涉及真实模型调用，耗时受网络与供应商影响，建议跑 2–3 次取中位数。
- 服务全部正常时重试数可能为 0（重试是兜底链路，正常不该触发），这不是脚本故障。
