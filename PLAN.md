# AI Agent 工具调用助手 — 实施方案 v2

> 范围：M2 ~ M6（本地运行；M6 不含部署）
> 计算器实现锁定：**sympy + 关键字黑名单**

---

## 0. 状态总览

| M | 目标 | 状态 |
|---|---|---|
| M1 | 脚手架（FastAPI + Next.js + shadcn/ui） | ✅ 已完成 |
| M2 | OpenAI Function Calling 三工具（天气/搜索/计算器） | ✅ 已完成 |
| M3 | LangGraph 多步任务编排 | ⏳ |
| M4 | 记忆（Checkpointer） | ⏳ |
| M5 | 错误恢复（重试） | ⏳ |
| M6 | UI 完善（不含部署） | ⏳ |

---

## 1. 总体技术选型

| 维度 | 选型 | 备注 |
|---|---|---|
| Agent 框架 | LangGraph（StateGraph + ToolNode） | M3 多步编排天然契合 |
| LLM | gpt-4o-mini（默认）/ gpt-4o | function calling 稳定 |
| 天气 | wttr.in（无需 key） | 失败可换 OpenWeatherMap |
| 搜索 | SerpAPI | 需求指定 |
| 计算器 | sympy + 关键字黑名单 | 已锁定 |
| 流式 | sse-starlette | 依赖已装 |
| 记忆 | SqliteSaver（本地）→ PostgresSaver（升级路径） | |
| 重试 | tenacity（指数退避） | |
| 部署 | **不做**（本地运行） | M6 仅做 UI |

---

## 2. 目录结构（M2 完成后）

```
backend/app/
├── agent/
│   ├── state.py          # AgentState (MessagesState + plan + steps)
│   ├── prompts.py        # 系统提示、planner prompt
│   ├── tools/
│   │   ├── weather.py    # @tool get_weather(city)
│   │   ├── search.py     # @tool web_search(query, num=5)
│   │   └── calculator.py # @tool calculate(expression)
│   ├── nodes.py          # planner / executor / aggregator
│   └── graph.py          # build_graph(checkpointer=...)
├── api/
│   ├── chat.py           # POST /api/chat (SSE)
│   ├── memory.py         # GET/DELETE /api/memory/{thread_id}
│   ├── threads.py        # GET /api/threads
│   └── echo.py           # 保留为调试
├── config.py
└── main.py

frontend/
├── app/
│   ├── page.tsx                # 聊天主页
│   ├── settings/page.tsx       # 模型 / 温度 / 重试上限
│   └── layout.tsx
├── components/
│   ├── chat/
│   │   ├── MessageBubble.tsx
│   │   ├── ToolCallCard.tsx
│   │   ├── PlanPanel.tsx
│   │   ├── StreamingDots.tsx
│   │   ├── ThreadSwitcher.tsx
│   │   └── EmptyState.tsx
│   └── ui/                     # shadcn
└── lib/
    ├── api.ts                  # echo → chat (SSE)
    ├── types.ts                # ChatMessage / ToolCall / TaskStep
    └── thread.ts               # localStorage thread_id 管理
```

---

## 3. M2 — 工具契约

### 3.1 `get_weather`
| 项 | 内容 |
|---|---|
| 入参 | `city: str` |
| 出参（成功） | `{city, temp_c, condition, humidity, wind_kph, observed_at}` |
| 出参（失败） | `{error: "city_not_found" \| "timeout" \| "upstream_error"}` |
| 实现 | `GET https://wttr.in/{city}?format=j1` → `current_condition[0]` |
| 超时 | 8s |
| 测试 | "上海" / "New York" / "不存在的城市xyz" |

### 3.2 `web_search`
| 项 | 内容 |
|---|---|
| 入参 | `query: str`, `num: int = 5`（1~10） |
| 出参 | `[{title, snippet, url}]` |
| 实现 | `serpapi.search(q=query, num=num)` |
| 缺 API key | 返回 `{error: "serpapi_key_missing"}`，不抛异常 |
| 测试 | "上海今天天气" / "LangGraph 教程" |

### 3.3 `calculate`
| 项 | 内容 |
|---|---|
| 入参 | `expression: str` |
| 出参（成功） | `{result: str, latex: str}` |
| 出参（失败） | `{error: "forbidden_keyword" \| "syntax_error" \| "evaluation_error"}` |
| 黑名单 | `__`, `import`, `os`, `sys`, `exec`, `eval(`, `open(`, `subprocess`, `lambda`, `;`, `\n` |
| 实现 | 黑名单预过滤 → `sympy.sympify(expr).evalf()` → `str` + `latex()` |
| 测试 | `2+2*3` / `sqrt(2)` / `import os` / `1/0` |

---

## 4. SSE 事件协议（M2 ~ M5 共用）

`POST /api/chat` 流式输出，Content-Type: `text/event-stream`：

| event | data | 含义 |
|---|---|---|
| `message_start` | `{id, role:"assistant", thread_id}` | 一条助手消息开始 |
| `content_delta` | `{delta}` | 文本片段 |
| `tool_call` | `{id, name, args}` | LLM 决定调用工具 |
| `tool_result` | `{id, ok, result?, error?, retry?, latency_ms}` | 工具执行回执 |
| `plan_update` | `{plan: TaskStep[]}` | M3：完整计划 |
| `step_update` | `{id, status}` | M3：单步状态切换 |
| `message_end` | `{finish_reason:"stop"\|"error"}` | 助手消息结束 |
| `error` | `{code, message, retriable}` | 全局错误 |

---

## 5. M3 — 多步编排

### 5.1 AgentState

```python
# backend/app/agent/state.py
from typing import Literal, Any
from langgraph.graph import MessagesState

class TaskStep(TypedDict):
    id: str                  # uuid4
    description: str         # 中文描述
    tool: str | None         # "get_weather" | "web_search" | "calculate" | None
    args: dict[str, Any]
    status: Literal["pending", "running", "done", "failed", "skipped"]
    result: Any
    error: str | None
    retry: int

class AgentState(MessagesState):
    plan: list[TaskStep]
    current_step: int        # -1 = 尚未规划
    final_answer: str | None
```

### 5.2 图结构

```
START
  ↓
planner_node          # LLM 生成 2~5 步计划
  ↓
executor_node         # 执行 plan[current_step]
  ↓
should_continue?      # cond edge
  ├── 未完且上一步 succeeded  → executor
  ├── 未完且上一步 failed + retry<3 → executor
  └── 已完 / 超限         → aggregator
                       ↓
                  aggregator_node   # 综合 plan 结果 → final_answer
                       ↓
                     END
```

### 5.3 planner prompt

```
你是任务规划器。把用户请求拆成 2~5 个原子步骤，每个步骤：
{ "id": "step-1", "description": "中文描述", "tool": "get_weather|web_search|calculate|null", "args": {} }
仅返回 JSON 数组，不要解释。
```

实现方式：先用 `response_format={"type": "json_object"}` 强约束；若不稳定再加一层正则兜底。

---

## 6. M4 — 记忆

### 6.1 thread_id 生命周期

| 阶段 | 行为 |
|---|---|
| 创建 | 首次访问 `crypto.randomUUID()`，存 `localStorage["agent.thread_id"]` |
| 切换 | 顶部下拉切换；新 thread 不继承旧消息 |
| 持久化 | `SqliteSaver.from_conn_string("data/checkpoints.db")` |
| 失效 | MVP 不做 TTL |
| 清空 | `DELETE /api/memory/{thread_id}` + 清空前端消息列表 |

### 6.2 API

| 方法 | 路径 | 说明 |
|---|---|---|
| POST | `/api/chat` | 必传 `thread_id`（不存在则 400） |
| GET  | `/api/memory/{thread_id}` | 返回消息历史 |
| DELETE | `/api/memory/{thread_id}` | 清空 |
| GET | `/api/threads` | 返回所有 thread + 最后活跃时间（M4 后期加） |

### 6.3 checkpointer

```python
# 开发
from langgraph.checkpoint.sqlite.aio import AsyncSqliteSaver
checkpointer = AsyncSqliteSaver.from_conn_string("data/checkpoints.db")

# 生产（升级路径）
from langgraph.checkpoint.postgres.aio import AsyncPostgresSaver
checkpointer = AsyncPostgresSaver.from_conn_string(DATABASE_URL)
```

---

## 7. M5 — 重试

### 7.1 重试范围

| 层级 | 行为 |
|---|---|
| 工具层（tenacity） | transient 错误：`httpx.HTTPError`, `RateLimitError`, `asyncio.TimeoutError`；max=3；指数 1s/2s/4s |
| 节点层（executor_node） | 永久错误（参数校验、黑名单命中）→ 直接 `failed`，**不**重试 |
| 任务层（plan step） | 步骤 `failed` → 标记 `skipped`，继续下一不阻塞 plan |
| LLM 层（OpenAI 调用） | tenacity 同工具层 |

### 7.2 UI 反馈

- `tool_result.retry > 0` → badge 显示 `🔁 重试 {n} 次后成功`
- `status === "failed"` → 红色，hover 显示 error
- `status === "skipped"` → 黄色，「因上一步失败而跳过」

---

## 8. 前端类型

```ts
// frontend/lib/types.ts
type Role = "user" | "assistant";

interface ChatMessage {
  id: string;
  role: Role;
  text: string;
  toolCalls: ToolCall[];
  plan?: TaskStep[];
  error?: { code: string; message: string };
}

interface ToolCall {
  id: string;
  name: string;
  args: Record<string, unknown>;
  status: "pending" | "running" | "ok" | "failed";
  result?: unknown;
  error?: string;
  retry?: number;
  latencyMs?: number;
}

interface TaskStep {
  id: string;
  description: string;
  tool?: string;
  status: "pending" | "running" | "done" | "failed" | "skipped";
}
```

---

## 9. M6 — UI 清单（不含部署）

### 9.1 shadcn 追加

`avatar` `badge` `separator` `sonner` `skeleton` `dialog` `dropdown-menu` `tooltip` `switch`

### 9.2 自研组件

| 组件 | 职责 |
|---|---|
| `MessageBubble` | 用户右对齐蓝底、助手左对齐白底；流式时半透明 |
| `ToolCallCard` | 单个 tool_call 折叠卡片：默认工具名 + 状态色 badge，展开看 args/result |
| `PlanPanel` | M3 抽屉：步骤清单 + checkbox 状态 |
| `StreamingDots` | LLM 生成中三点动画 |
| `ThreadSwitcher` | 顶部下拉：切换 thread、`+ 新会话`、清空 |
| `EmptyState` | 无消息时的引导文案 + 三个示例 prompt |

### 9.3 交互

- 长消息自动折叠（>300 字）
- 自动滚动到底部（新消息 / 流式）
- 流式中断：取消按钮 + AbortController
- 单条消息重发（重放同 thread_id）
- 暗色模式：跟随系统 + 顶部手动切换

---

## 10. 工期

| M | 估计 |
|---|---|
| M2 工具 + 单步 graph + SSE | 1 天 |
| M3 多步编排 | 1 天 |
| M4 记忆 | 0.5 天 |
| M5 重试 | 0.5 天 |
| M6 UI 完善（不含部署） | 0.5 天 |
| **合计** | **3.5 天** |

---

## 11. 待确认（开始 M2 前）

1. **SSE 事件协议** 是否照第 4 节清单实现？
2. **planner JSON 强约束**：用 OpenAI `response_format`（稳）还是仅 prompt（省 token）？
3. **M3 单步失败**：当前「跳过继续」 vs 「终止整 plan」？