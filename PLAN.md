# AI Agent 工具调用助手 — 实施方案 v2

> 范围：M2 ~ M6（本地运行；M6 不含部署）
> 计算器实现锁定：**sympy + 关键字黑名单**

---

## 0. 状态总览

| M | 目标 | 状态 |
|---|---|---|
| M1 | 脚手架（FastAPI + Next.js + shadcn/ui） | ✅ 已完成 |
| M2 | OpenAI Function Calling 三工具（天气/搜索/计算器） | ✅ 已完成 |
| M3 | LangGraph 多步任务编排 | ✅ 已完成 |
| M4 | 记忆（Checkpointer） | ✅ 已完成 |
| M5 | 错误恢复（重试） | ✅ 已完成 |
| M6 | UI 完善（不含部署） | ✅ 已完成 |
| 附加 | RAG 接入（外部文档检索工具） | ✅ 已完成 |

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

### 3.4 `search_docs`（RAG 接入后新增，详见 §18）
| 项 | 内容 |
|---|---|
| 入参 | `query: str`, `top_k: int = 5`（1~10）, `doc_id: str \| None` |
| 出参（成功） | `{results: [{source, page, text, similarity, doc_id}], count, sources}` |
| 出参（失败） | `{error: "empty_query" \| "rag_not_configured" \| "rag_timeout" \| "rag_unavailable" \| "rag_error"}` |
| 实现 | `httpx` → `POST {RAG_API_URL}/api/search`（外部 RAG 服务） |
| 超时 | 30s |
| 备注 | 失败不抛异常，返回错误字典让 LLM 改用别的方案 |

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

1. **SSE 事件协议** 是否照第 4 节清单实现？ → 已按第 4 节实现
2. **planner JSON 强约束**：用 OpenAI `response_format`（稳）还是仅 prompt（省 token）？
   → 已用 `response_format={"type": "json_object"}`，实测 3/3 可解析
3. **M3 单步失败**：当前「跳过继续」 vs 「终止整 plan」？ → 已选「跳过继续」

---

## 12. M3 实施补充（M2 → M3 的变更）

### 12.1 与原计划的三处偏差

| 项 | 原计划 | 实际实现 | 原因 |
|---|---|---|---|
| executor 执行方式 | 计划里带 tool+args，executor 执行 | 同上，但**参数名按工具 schema 自动归一化** | 实测 planner 会把 `city` 写成 `location` |
| 流式模式 | 未明确 | 只用 `stream_mode="custom"` | `"messages"` 模式会把 planner 的 JSON 也当正文推给前端 |
| 正文来源 | aggregator 产出 final_answer | aggregator 内部 `astream` 逐 token 推 `delta` 事件 | 避免混流，正文只来自汇总器 |

### 12.2 新增事件

| event | data | 含义 |
|---|---|---|
| `plan_update` | `{plan: TaskStep[]}` | planner 生成的完整计划 |
| `step_update` | `{id, status, description, tool}` | 单步状态切换 |

`tool_result` 在 M3 里结构有变：多了 `name` 和 `args`，`id` 是**步骤 ID**（`step-1`）而不是 M2 的 tool_call id。

### 12.3 文件结构变化

```
backend/app/agent/
├── state.py       # 扩展：TaskStep / plan / current_step / final_answer
├── prompts.py     # 新增：PLANNER_PROMPT / AGGREGATOR_PROMPT
├── nodes.py       # 新增：planner / executor / aggregator
├── text.py        # 新增：ThinkFilter（从 api/chat.py 抽出）
└── graph.py       # 改为 M3 图结构

frontend/components/chat/
└── PlanPanel.tsx  # 新增：任务计划面板
```

### 12.4 参数名归一化

planner 输出的参数名不可信，executor 执行前会按工具 schema 校正：

| 别名 | 修正为 |
|---|---|
| `location` / `place` / `city_name` | `city` |
| `keyword` / `q` / `search` | `query` |
| `expr` / `formula` / `text` | `expression` |

不在白名单里的参数会被直接丢弃，避免传给工具时报错。

---

## 13. M4 实施补充（M3 → M4 的变更）

### 13.1 关键实现要点

**checkpointer 必须在整个应用生命周期内持有连接。**
`AsyncSqliteSaver.from_conn_string` 是 async context manager，用完连接就断。
所以 `checkpointer.py` 里自己用 `aiosqlite` 建连接再包一层，
由 FastAPI 的 lifespan 负责开关。

**光有 checkpointer 不够 —— 必须把历史放进提示词。**
这是 M4 最大的坑：checkpointer 确实把历史消息存进了 state，
但 planner 和 aggregator 原来都只取「最后一条 HumanMessage」，
模型根本看不到之前聊过什么，于是回答「我不知道你的名字」。

修复：新增 `text.py` 的 `extract_conversation(messages)`，
返回 `(当前问题, 历史对话)`，planner 和 aggregator 都用它拼 messages 列表。

### 13.2 与原计划的两处偏差

| 项 | 原计划 | 实际实现 | 原因 |
|---|---|---|---|
| checkpointer 生命周期 | `AsyncSqliteSaver.from_conn_string` | 自己管 aiosqlite 连接 + lifespan | 原写法用完即断 |
| 前端会话列表 | 后端 `/api/threads` 提供 | 后端提供接口，前端在 localStorage 另存一份 | 前端要能离线显示会话名 |

### 13.3 新增文件

```
backend/app/agent/
└── checkpointer.py   # SqliteSaver 管理 + lifespan 作用域

backend/app/api/
├── memory.py         # GET/DELETE /api/memory/{thread_id}
└── threads.py        # GET /api/threads

frontend/components/chat/
└── ThreadSwitcher.tsx  # 会话切换器（原生 select，不新增依赖）
```

### 13.4 API 契约变更

`POST /api/chat` 的 `thread_id` 从**可选**变为**必传**（缺失返回 422）。

---

## 14. M5 实施补充（M4 → M5 的变更）

### 14.1 三个关键实现要点

**重试判定是白名单式的，不是「捕获所有异常」。**
可重试的只有三类：网络抖动（httpx 超时/连接失败）、限流（429）、上游 5xx。
参数写错、表达式有黑名单词、鉴权失败 —— 这些重试一万次也是同样的错，
所以它们命中 `PERMANENT_EXCEPTIONS`，一次都不重试。

**工具失败有两种形态，重试层要同时处理。**
三个工具都是自己吞掉异常、返回 `{"error": "timeout"}`，
所以光靠 `retry_if_exception` 是不够的 —— 还得用 `retry_if_result`
判返回值。两个条件是「或」的关系。

**关掉 openai SDK 的内置重试，让 tenacity 当唯一的重试层。**
`ChatOpenAI(max_retries=0)`。否则 SDK 内部重试 2 次 × tenacity 重试 3 次
= 最多 16 次调用，而且用户看不到 SDK 内部重试了几次 ——
「重试 N 次」的徽章就不准了。

### 14.2 tenacity 的两个坑（实测踩到）

**坑 1：结果型重试耗尽会丢错误码。**

工具失败返回 `{"error": "timeout"}`，但 `reraise=True` 时
tenacity 抛的是 `RetryError` —— 里面只包了个 Future，
真正的错误码拿不到了。

解决：用 `retry_error_callback` 把最后一次的结果原样返回，
不抛 `RetryError`。

**坑 2：`before_sleep` 才是重试次数的正确来源。**

`retry_state.attempt_number` 在 `before_sleep` 回调里表示的是
「即将进行的第几次尝试」，直接拿来当「已重试次数」会算错。
数 `before_sleep` 的调用次数才是准确的。

### 14.3 与原计划的三处偏差

| 项 | 原计划 | 实际实现 | 原因 |
|---|---|---|---|
| 步骤失败的状态 | `failed` → 标记 `skipped` | `failed` 保持 failed，后续步骤照常执行 | `skipped` 原意是"因上一步失败而跳过"，但混用后分不清"失败了"和"没执行"。已与用户确认：失败那步标红（failed），只有"没法执行"（工具不存在/参数非法）才标黄（skipped） |
| 失败状态是否阻塞 | 两种说法并存 | **不阻塞** | 用户确认：独立步骤不该因为别的步骤失败而丢失结果 |
| 工具错误码分类 | 按异常类型分类 | 额外按**返回值**分类 | 三个工具都吞掉异常返回错误字典，只看异常永远看不到 transient 失败 |

### 14.4 状态语义（M5 最终版）

| 状态 | 含义 | 颜色 | 是否阻塞后续 |
|---|---|---|---|
| `done` | 成功 | 绿 | — |
| `failed` | 执行了但没成功（重试耗尽 / 工具报错） | 红 | ❌ 不阻塞 |
| `skipped` | 根本没法执行（工具不存在 / 参数非法） | 黄 | ❌ 不阻塞 |

### 14.5 新增文件

```
backend/app/agent/
└── retry.py             # 重试策略核心：错误分类 + tenacity 封装

backend/tests/
├── test_retry.py        # 错误分类 + 重试行为（34 个）
└── test_nodes_retry.py  # executor 的 failed/skipped 语义（10 个）
```

### 14.6 新增 SSE 事件

| event | data | 含义 |
|---|---|---|
| `retry` | `{layer, stage, attempt, max_attempts, message}` | 正在重试（layer: tool / llm） |

同时给已有事件加了字段：

| event | 新增字段 |
|---|---|
| `tool_result` | `retry` — 重试了几次 |
| `step_update` | `retry` — 重试了几次；`error` — 失败原因 |
| `plan_update` | 每个 step 带 `retry` |

### 14.7 配置

`backend/.env` 可加 `RETRY_MAX_ATTEMPTS`（默认 3，即最多尝试 4 次）。

---

## 15. M6 实施计划（UI 完善，不含部署）

> 已与用户确认的两个决策：
> 1. **设置页纯前端** —— 设置存 localStorage，随请求发给后端，不做后端持久化
> 2. **shadcn CLI 安装组件** —— 联网装 @radix-ui/* 包

### 15.1 先修一个必须修的 Bug：暗色模式根本不生效

M1~M5 的代码里已经写了 8 处 `dark:` 类（如 `dark:text-red-400`），
但**它们从来没生效过**。

原因：Tailwind v4 的 `dark:` 变体默认驱动方式是 `@media (prefers-color-scheme: dark)`，
不是类名。而 `globals.css` 里写的是 `.dark { ... }` —— 需要手动给 `<html>` 加 `.dark` 类。

实测确认：

```
# 默认：生成 prefers-color-scheme 媒体查询（无法手动切换）
grep -c "prefers-color-scheme" 输出 → 1

# 加 @custom-variant 后：生成 .dark 类选择器（可手动切换）
@custom-variant dark (&:is(.dark *));
→ .probe { color: var(--color-red-600); &:is(.dark *) { color: var(--color-red-400); } }
```

**修复**：在 `globals.css` 里加一行

```css
@custom-variant dark (&:is(.dark *));
```

这一行是整个 M6 暗色模式的地基 —— 不加的话，做多少暗色 UI 都是白费。

### 15.2 任务清单

| # | 任务 | 涉及文件 | 说明 |
|---|---|---|---|
| T1 | 暗色模式地基 | `app/globals.css` | 加 `@custom-variant dark` |
| T2 | 主题切换器 | `components/theme-toggle.tsx`（新） | 跟随系统 / 亮 / 暗 三态，存 localStorage |
| T3 | 安装 shadcn 组件 | `components/ui/*` | badge / avatar / separator / skeleton / tooltip / dropdown-menu |
| T4 | 组件归一化 | `components/ui/*` | CLI 装出来的组件要用 `@/lib/utils` 和 `@radix-ui/react-slot`，不能引 `cn` 和 `radix-ui` 包 |
| T5 | 空状态 | `components/chat/EmptyState.tsx`（新） | 无消息时的引导 + 3 个示例 prompt，点击即填入 |
| T6 | 头像与消息气泡 | `components/chat/MessageBubble.tsx` | 用 avatar 组件替换"你/Agent"文字 |
| T7 | 流式三点动画 | `components/chat/StreamingDots.tsx`（新） | 生成中指示器 |
| T8 | 长消息折叠 | `components/chat/MessageBubble.tsx` | >300 字折叠，展开按钮 |
| T9 | 自动滚动 | `app/page.tsx` | 新消息/流式时滚到底部 |
| T10 | 单条重发 | `app/page.tsx` + `components/chat/MessageBubble.tsx` | 重放同 thread_id |
| T11 | 设置页 | `app/settings/page.tsx`（新） + `lib/settings.ts`（新） | 模型/温度/重试上限 |
| T12 | 设置贯通到请求 | `lib/api.ts` + `backend/app/api/chat.py` | 随请求发给后端 |

### 15.3 T11/T12：设置页的完整链路

纯前端设置的关键设计 —— **后端要能按请求覆盖配置**。

```
设置页（lib/settings.ts，存 localStorage）
  ↓
POST /api/chat {message, thread_id, model?, temperature?, retry_max_attempts?}
  ↓
backend/app/api/chat.py  ← 校验并透传
  ↓
backend/app/agent/graph.py ← 运行时注入
  ↓
nodes.py 的 _model() / retry.py 读注入值而不是全局配置
```

**关键约束**：全局 `get_settings()` 里的值是**默认值**，
请求里带的值是**覆盖值**。两者要分层，不能让请求直接改全局状态
（否则并发请求会互相污染）。

实现方式：把覆盖值放进 LangGraph 的 `config` 里（`configurable`），
节点里用 `get_config()` 取出来。这样每个请求独立，互不影响。

```python
# graph.py
config = {
    "recursion_limit": RECURSION_LIMIT,
    "configurable": {
        "thread_id": thread_id,
        "model": model,                    # 覆盖全局
        "temperature": temperature,
        "retry_max_attempts": retry_max_attempts,
    },
}
```

```python
# nodes.py 的 _model()
def _model(temperature: float | None = None) -> ChatOpenAI:
    overrides = get_config().get("configurable") or {}
    model_name = overrides.get("model") or get_settings().openai_model
    temp = overrides.get("temperature") if temperature is None else temperature
    ...
```

> 注意：`temperature` 在 planner（0.2）和 aggregator（默认）里用法不同，
> 覆盖时要用**相对偏移**还是**绝对值**需要定清楚。
> 建议：设置页的滑块直接对应 aggregator 的温度，planner 固定 0.2
> （planner 要稳定，聚合器要发散）。

### 15.4 T4：shadcn CLI 装的组件需要归一化（实测发现）

shadcn CLI 4.23 装出来的组件用的是**最新 registry 风格**：

```tsx
import { cn } from "cn"          // ← 新包
import { Slot } from "radix-ui"   // ← 统一包（会拖进 50+ 个 radix 依赖）
```

而本项目现有约定是：

```tsx
import { cn } from "@/lib/utils"
import { Slot } from "@radix-ui/react-slot"
```

**实测结论**：CLI 会往 package.json 里加 `cn` 和 `radix-ui` 两个包，
其中 `radix-ui` 是个 meta 包，把 50+ 个 radix 组件全装进来 —— 而我们只要用 6 个。

**处理方式**：

1. CLI 装完后，逐个把 `from "cn"` → `from "@/lib/utils"`、
   `from "radix-ui"` → `from "@radix-ui/react-slot"`
2. `npm uninstall cn radix-ui`
3. 单独装真正需要的：`@radix-ui/react-avatar`、`@radix-ui/react-tooltip`、
   `@radix-ui/react-dropdown-menu`、`@radix-ui/react-separator`、`@radix-ui/react-skeleton`

> `badge` 已经实测过一遍：归一化后 TSC 通过，依赖回到原样。

### 15.5 组件清单（对照 §9）

| §9 计划里的组件 | 现状 | M6 动作 |
|---|---|---|
| `MessageBubble` | 已有 | 改：加 avatar、长消息折叠、重发按钮 |
| `ToolCallCard` | 已有 | 改：状态徽章换成 shadcn `Badge` |
| `PlanPanel` | 已有 | 不动（M5 已完善） |
| `StreamingDots` | 无 | 新建 |
| `ThreadSwitcher` | 已有 | 改：换成 shadcn `DropdownMenu`（原生日 select 移动端体验差） |
| `EmptyState` | 无 | 新建 |
| `avatar` | 无 | shadcn 安装 |
| `badge` | 已装 | 归一化 |
| `separator` | 无 | shadcn 安装 |
| `sonner` | 无 | **不装** —— 用轻量 toast 替代，见 15.7 |
| `skeleton` | 无 | shadcn 安装 |
| `dialog` | 无 | **不装** —— 确认删除会话用 `window.confirm` 够了 |
| `dropdown-menu` | 无 | shadcn 安装（替换原生 select） |
| `tooltip` | 无 | shadcn 安装 |
| `switch` | 无 | shadcn 安装（设置页用） |

### 15.6 交互清单（对照 §9.3）

| 项 | 实现要点 |
|---|---|
| 长消息自动折叠（>300 字） | `MessageBubble` 内判断长度，超了就截断 + 「展开」按钮 |
| 自动滚动到底部 | `ScrollArea` 的 viewport 拿到 ref，`messages.length` 变化时 `scrollTop = scrollHeight`。**注意**：流式过程中每个 delta 都滚会抖，要节流 |
| 流式中断 | 已有 `AbortController` + 「停止」按钮，✅ 已完成 |
| 单条消息重发 | 「重发」按钮 → 拿原消息内容重发，**同 thread_id**（这样记忆是连贯的） |
| 暗色模式 | T1 + T2，三态切换 |

### 15.7 两处主动缩减（避免过度工程）

**不做 `sonner`** —— 它要装 `next-themes` 之外的一堆依赖，
而本项目的 toast 需求只有两种：「已复制」「设置已保存」。
用 10 行代码 + `useState` 做一个轻量 Toast 更合适。

**不做 `dialog`** —— 唯一用途是确认删除会话。
`window.confirm` 一行搞定，不值得引入一个组件 + Portal 体系。

### 15.8 实施顺序

```
T1 暗色地基  ← 必须最先做，否则后面全是白工
  ↓
T3+T4 shadcn 安装 + 归一化
  ↓
T2 主题切换器
  ↓
T5~T8 聊天区组件（空状态、头像、动画、折叠）
  ↓
T9+T10 交互（自动滚动、重发）
  ↓
T11+T12 设置页 + 后端贯通  ← 工作量最大，单独一块
```

### 15.9 验收标准

| 项 | 怎么验 |
|---|---|
| 暗色模式真的生效 | 切到暗色，`.dark` 类出现在 `<html>` 上，截图对比亮/暗 |
| 设置项真的贯通 | 设置温度为 0，改模型名，后端日志能看到实际用的值 |
| 8 处旧 `dark:` 类生效 | 打开暗色，失败步骤的红色文字变浅（`dark:text-red-400`） |
| 没有引入多余依赖 | `package.json` 只多出明确列出的 5 个 radix 包 + next-themes |
| 类型检查通过 | `npx tsc --noEmit` 无错误 |
| 后端回归 | `pytest` 全绿（后端只改了 chat.py 的请求模型） |

### 15.10 风险与预案

| 风险 | 预案 |
|---|---|
| shadcn CLI 装的组件风格和项目不一致 | 已实测：逐个改 import + 卸载 `cn`/`radix-ui` 即可 |
| 自动滚动在流式时抖动 | 用 `requestAnimationFrame` 节流，或只在「用户已贴底」时才自动滚 |
| 设置页的模型名是用户瞎填的 | 后端校验失败要返回清晰的错误码，不能 500 |
| `temperature` 覆盖影响 planner | planner 固定 0.2，只让 aggregator 接受覆盖 |

---

## 16. M6 实施补充（计划 → 实际）

### 16.1 实施中发现并修掉的老 Bug：暗色模式从未生效

M1~M5 的代码里有 8 处 `dark:` 类（`dark:text-red-400` 等），
但它们**一次都没生效过** —— 写的时候以为能用，实际全是哑弹。

原因：Tailwind v4 的 `dark:` 默认是 `@media (prefers-color-scheme: dark)`，
而 `globals.css` 写的是 `.dark { ... }` 类。两者对不上。

**修复**（一行）：

```css
@custom-variant dark (&:is(.dark *));
```

实测验证（浏览器确认）：错误文字在亮色下是 `rgb(231,0,11)`（red-600），
切到暗色变成 `rgb(255,100,103)`（red-400）—— 证明 `dark:` 变体真正命中了。

> 这个 bug 值得单独记一笔：**没有验证过的 UI 代码等于没写**。
> M1~M5 一直只做后端测试，前端的 `dark:` 类从没被真正检验过。

### 16.2 shadcn CLI 的两个坑（实测）

**坑 1：CLI 装出来的组件用的是最新 registry 风格。**

```tsx
import { cn } from "cn"          // ← 新包，项目用的是 @/lib/utils
import { Slot } from "radix-ui"   // ← meta 包，会拖进 50+ 个 radix 依赖
```

**坑 2：不能用具名导入拆包。**

CLI 的代码用的是 `AvatarPrimitive.Root` 这种命名空间访问，
换成 `import { Avatar } from "@radix-ui/react-avatar"` 后
`Avatar.Root` 就不存在了 —— TSC 直接报 20+ 个错。

**正确解法**：

```tsx
import * as AvatarPrimitive from "@radix-ui/react-avatar"   // 命名空间
import { Slot } from "@radix-ui/react-slot"                 // Slot 例外，它本身就是组件
```

装完再 `npm uninstall cn radix-ui`，单独装真正需要的 5 个 radix 包。

### 16.3 设置项的并发安全：为什么要走 configurable

设置页是纯前端的（存 localStorage，随请求发给后端），
所以后端必须能**按请求**覆盖配置。

如果直接改全局 `get_settings()` 的值，会有两个问题：
1. 并发请求互相污染 —— A 请求改了模型名，B 请求跟着变了
2. 改完就一直生效，没法回退

**解法**：把覆盖值放进 LangGraph 的 `configurable`，节点用 `get_config()` 取。

```python
# chat.py
configurable = {"thread_id": thread_id}
if overrides.model:
    configurable["model"] = overrides.model
# ...
config={"recursion_limit": 50, "configurable": configurable}
```

```python
# nodes.py
def _overrides() -> dict[str, Any]:
    try:
        config = get_config()
    except Exception:
        return {}          # 不在图里跑（单元测试）时兜底
    return (config.get("configurable") or {})
```

每个请求独立，天然并发安全。

### 16.4 温度的语义：planner 固定，aggregator 可调

设置页的「温度」滑块只影响 **aggregator**（写最终回答），
**planner 固定 0.2**。

原因：planner 的职责是「把同样的问题拆成同样的步骤」——
温度高了会导致每次拆解结果不同，行为不可预测。
aggregator 是写最终回答，温度高一点更自然。

```python
# planner：固定
return await _model(temperature=0.2).ainvoke(...)

# aggregator：用请求里的值（没传则用默认）
model = _model()
```

### 16.5 自动滚动的两个细节

**细节 1：Radix ScrollArea 不透传 viewport 的 ref。**
自动滚动要直接操作 `scrollTop`，所以给 ScrollArea 加了个 `viewportRef` prop。

**细节 2：只在「用户本来就贴着底部」时才自动滚。**

```tsx
const distance = el.scrollHeight - el.scrollTop - el.clientHeight;
setPinnedToBottom(distance < 32);   // 留 32px 余量
```

留余量的原因：滚动动画的最后一点点位移如果按 0 判断，
会误判成「用户上翻了」，然后自动滚动就失效了。

实测：流式期间 `distFromBottom` 始终为 0 —— 确认跟随。

### 16.6 新增文件

```
frontend/app/settings/page.tsx     # 设置页
frontend/lib/settings.ts           # 设置存取（localStorage）
frontend/components/
├── theme-provider.tsx             # next-themes 封装
├── theme-toggle.tsx               # 三态主题切换
└── chat/
    ├── EmptyState.tsx             # 空状态 + 示例 prompt
    └── StreamingDots.tsx          # 流式三点动画

frontend/components/ui/            # shadcn 安装（已归一化）
├── avatar.tsx  badge.tsx  separator.tsx
├── skeleton.tsx  tooltip.tsx  dropdown-menu.tsx  switch.tsx

backend/tests/
└── test_settings.py               # 设置贯通（11 个）
```

### 16.7 主动砍掉的部分

| 组件 | 原因 |
|---|---|
| `sonner` | toast 需求只有「已保存」一种，10 行 state 够用 |
| `dialog` | 唯一用途是确认删除会话，`window.confirm` 一行搞定 |
| `switch` | 装了但没用上 —— 设置项都是滑块/输入框，没有开关 |

### 16.8 最终状态

| 项 | 结果 |
|---|---|
| 后端测试 | 103 个通过（含新增 11 个设置测试） |
| 前端类型检查 | 通过 |
| 浏览器回归 | 9 项特性全部通过，无 console 错误 |
| 新增依赖 | 5 个 radix 包 + next-themes（无 `cn`、无 `radix-ui` meta 包） |

---

## 17. M6 补充：模型切换 + 多 provider

### 17.1 起因：之前的「切换模型」其实是假的

用户问「你做的那个切换模型有用吗？」—— 实测发现**没用**。

前端设置页能改模型名，但后端只有一个全局的 `OPENAI_BASE_URL`，
所以换个模型名的同时 base_url 还是老的。实测：

```
model=gpt-4o-mini（但 base_url 指向 MiniMax）
→ OpenAIInvalidRequestError: 400 - invalid params, unknown model 'gpt-4o-mini'
```

**切换模型名 ≠ 切换服务商。** 这是 M6 最初设计里的根本缺陷。

### 17.2 解法：按模型名路由到 provider

新增 [providers.py](file:///Users/xinao/Desktop/ai-project/agent-tool-assistant/backend/app/agent/providers.py)：

```
模型名以 "deepseek" 开头 → DEEPSEEK_BASE_URL + DEEPSEEK_API_KEY
模型名以 "minimax" 开头 → OPENAI_BASE_URL  + OPENAI_API_KEY
其它                    → 默认 provider
```

DeepSeek 也是 OpenAI 兼容格式，所以只是换了 base_url 和 key。

**没配 key 时抛 `ProviderNotConfigured`**，而不是让上游报含糊的 401：

```
"DeepSeek 还没配置 API Key。请在 backend/.env 里设置对应的环境变量（DEEPSEEK_API_KEY）后重启后端。"
```

### 17.3 模型列表改由后端提供

**前端不再硬编码模型列表。** 之前硬编码过一份（gpt-4o-mini / gpt-4o / MiniMax-M3），
但后端的 base_url 指向 MiniMax —— 选 gpt-4o 必然报错。

硬编码的列表和后端配置很容易对不上。现在由 `GET /api/models` 提供：

```json
{
  "default_model": "MiniMax-M3",
  "providers": [
    { "id": "minimax", "configured": true, "models": [...] },
    { "id": "deepseek", "configured": false, "models": [...] }
  ]
}
```

前端按 `configured` 把没配 key 的 provider 置灰禁用 —— 选了只会得到 401。

### 17.4 顺带修掉的一个 UI 遮挡问题

Next.js 开发浮标（`nextjs-portal`）会盖住模型切换器的图标区
（`position: fixed` + `z-index: 2147483647`），点图标点不到。

修复：`next.config.ts` 里 `devIndicators: false`。

### 17.5 DeepSeek 启用方式（留的口子）

```bash
# backend/.env
DEEPSEEK_API_KEY=sk-xxxxxxxx
DEEPSEEK_BASE_URL=https://api.deepseek.com
DEEPSEEK_MODEL=deepseek-v4-pro
```

填完**重启后端**（配置是启动时读的）。前端会自动检测到并解锁该 provider。

可用模型：`deepseek-v4-pro` / `deepseek-v4-flash` / `deepseek-chat` / `deepseek-reasoner`。

### 17.6 新增文件

```
backend/app/agent/providers.py       # provider 解析与路由
backend/app/api/models.py             # GET /api/models
backend/tests/test_providers.py       # provider 路由（16 个）

frontend/components/chat/ModelSwitcher.tsx   # 输入框旁的切换器
```

### 17.7 关于「前端硬编码 vs 后端提供」的教训

模型名和「配没配 key」都是**后端状态** —— 前端无从得知。
凡是这类「取决于服务端配置」的清单，都应该由后端提供接口，
否则两边一定会漂移。

M6 最初把模型名硬编码在前端，是一次典型的「看起来能用、实际是哑弹」的设计。

---

## 18. RAG 接入（外部文档检索）

### 18.1 起因

用户：「我有一个 rag 的文档系统，能接入进来吗？」

已有的 RAG 项目：`/Users/xinao/Desktop/ai-project/doc-analysis-rag`
（FastAPI + Chroma + 本地 HuggingFace `BAAI/bge-small-zh-v1.5`，7 篇文档 / 20 个向量）

### 18.2 两种接法的取舍（用户已确认选 A）

| | A. HTTP（**已选**） | B. 直接 import 内部函数 |
|---|---|---|
| 耦合 | 靠一个 JSON 契约解耦 | 绑死对方的模块结构和路径 |
| 部署 | 两个服务独立起 | 必须同进程、同一 venv |
| 对方改动 | 不影响 agent | 内部重构就可能崩 |
| 延迟 | 多一次本地 HTTP（~1ms 量级） | 进程内调用 |
| 能力边界 | 只能用对方暴露出来的 | 能直接调内部函数 |

RAG 项目本身就是独立部署的 FastAPI 服务，加 HTTP 端点是最自然的接法。

### 18.3 RAG 项目侧：新增 `POST /api/search`

**只做检索，不生成答案。**

RAG 自己的 `/api/chat` 是「检索 + 生成」打包的，但 agent 本来就要自己调 LLM 汇总 ——
走那条路等于跑两次 LLM（成本翻倍、延迟叠加），而且拿到的已是二手答案，没法溯源。

新增 [search.py](file:///Users/xinao/Desktop/ai-project/doc-analysis-rag/backend/app/api/search.py)：

```
请求  {"query": str, "top_k": int = 5, "doc_id": str | null}
响应  {"results": [...], "count": int, "sources": [str]}
```

每条 result 的结构：

```json
{
  "doc_id": "9e54...",
  "chunk_index": 2,
  "page": 1,
  "source": "prd-rules.md",
  "text": "...",
  "score": 0.9227,
  "similarity": 0.5743,
  "rerank_score": 0.4902
}
```

- `score` 是 Chroma 的 L2 距离（越小越相似）
- `similarity` 是换算后的余弦相似度（越大越相似）
- `rerank_score` 有值说明过了 cross-encoder 重排；模型不可用时降级返回前 top_k

### 18.4 端口：RAG 从 8000 改到 8001

agent 后端占着 8000。RAG 项目把 `APP_PORT` / `vite` 代理 / 前端 API base
统一改到 8001（`package.json`、`start-backend.sh`、`.env`、`.env.example`、`vite.config.ts`、`src/lib/api.ts`）。

### 18.5 agent 侧：`search_docs` 工具

新增 [rag.py](file:///Users/xinao/Desktop/ai-project/agent-tool-assistant/backend/app/agent/tools/rag.py)：

| 项 | 内容 |
|---|---|
| 入参 | `query: str`, `top_k: int = 5`（钳到 1~10）, `doc_id: str \| None` |
| 出参（成功） | `{results: [{source, page, text, similarity, doc_id}], count, sources}` |
| 出参（失败） | `{error: "empty_query" \| "rag_not_configured" \| "rag_timeout" \| "rag_unavailable" \| "rag_error"}` |
| 实现 | `httpx.AsyncClient` → `POST {RAG_API_URL}/api/search` |
| 超时 | 30s |

**裁剪**：单个 chunk 最多留 1500 字符。
一个 chunk 可能上千字，全塞进提示词会挤爆上下文 —— 完整的原文可以再查一次。

**失败也返回字典，不抛异常** —— 和另外两个工具一致：
工具失败不能让整个链路崩掉，要让 LLM 读到「搜不了」然后改用别的方案。

### 18.6 重试层的契约

`rag_timeout` / `rag_unavailable` 加进 `is_transient_tool_result` 的可重试码
（和 `timeout` / `upstream_error` 同级）。

`rag_not_configured` / `empty_query` **不重试** —— 重试也没用。

### 18.7 planner 的提示词

```
- search_docs: 参数 {"query": "检索关键词", "top_k": 5, "doc_id": null}，在内部文档库中检索原文片段

规则：
5. 涉及内部文档、PRD、规范、规则、字段定义等公司/项目内部资料的问题，必须先用 search_docs 检索；
   只有当问题明确指向互联网公开信息（如天气、实时新闻）时才用 web_search
6. search_docs 的 query 要用文档里可能出现的术语或原文片段，不要用口语化的整句提问
```

第 5 条是关键 —— 不然 planner 会把「金额类字段用什么类型」也丢给 `web_search`，
去网上搜数据库设计规范，而不是查公司自己的 PRD。

### 18.8 配置

```bash
# backend/.env
RAG_API_URL=http://localhost:8001
```

留空 = 不启用，`search_docs` 返回 `{"error": "rag_not_configured"}`。

### 18.9 端到端实测结果

问「金额类字段推荐用什么类型？」：

```
plan_update  step-1 = search_docs(query="金额 字段 类型 金额类", top_k=5)
step_update  step-1 running → done
tool_result  ok=true, count=5, sources=["prd-rules.md", "三方施工统计分析-行业监管部门页面说明.md"]
             命中片段含「金额类 / 单价、总额 / DECIMAL(16,2)」

最终回答：金额类字段（如单价、总额）推荐使用 DECIMAL(16,2)，
         避免使用 FLOAT/DOUBLE，以保证金额计算的准确性。
```

反例「今天北京天气怎么样？」→ 走 `get_weather`，不触发 `search_docs`。

### 18.10 顺带修掉的两个既有 bug

**Bug 1：SSE 的 step 事件被后续修改污染。**

`writer()` 传出去的是**引用**。executor 把同一个 dict 传了两次
（`running` 一次、`done` 一次），两次推送之间没有 `await`，
消费端序列化时看到的已经是最终值 —— **`running` 状态凭空消失**。

修法：`writer({"event": "step", "step": dict(step)})` —— 传副本。

这个 bug 从 M3 就有，只是之前无工具步骤（`tool=null`）会连续推两次相同状态，
肉眼看不出来。接入 RAG 后步骤变多、用户会盯着「正在检索文档」，
才暴露出来。回归测试见 `test_executor_step_events_are_snapshots`。

**Bug 2：`TOOL_LABELS` 抄了两份。**

`PlanPanel.tsx` 和 `ToolCallCard.tsx` 各有一份工具名 → 中文名的映射。
加 `search_docs` 时漏改 PlanPanel 那份，导致计划面板不显示「文档检索」标签
（浏览器实测发现）。修法：抽到 `frontend/lib/types.ts` 统一导出。

### 18.11 前端展示

`ToolCallCard` 对 RAG 结果做了专门渲染 —— 而不是甩一大坨 JSON：

- 收起时多一个「N 条片段」徽章
- 展开后逐条显示：来源文件名 / 页码 / 相似度 / 正文

### 18.12 新增文件

```
backend/app/agent/tools/rag.py     # search_docs 工具
backend/tests/test_rag.py           # 15 个测试

frontend/lib/types.ts               # 统一导出 TOOL_LABELS
```

（doc-analysis-rag 侧：`backend/app/api/search.py`）
