# AI Agent 工具调用助手

渐进式 AI Agent 项目，6 个里程碑逐步搭建：

| M | 目标 | 状态 |
|---|---|---|
| M1 | 脚手架（FastAPI + Next.js + LangGraph） | ✅ 已完成 |
| M2 | OpenAI Function Calling 三工具（天气/搜索/计算器） | ✅ 已完成 |
| M3 | LangGraph 多步任务编排 | ✅ 已完成 |
| M4 | 记忆（Checkpointer） | ✅ 已完成 |
| M5 | 错误恢复（重试） | ✅ 已完成 |
| M6 | UI 完善（不含部署） | ✅ 已完成 |

## 架构

```
agent-tool-assistant/
├── backend/          # Python FastAPI + LangGraph
└── frontend/         # Next.js + shadcn/ui
```

## 快速启动

### 1. 一次性安装

```bash
# 根目录：安装 concurrently（并行启动用）
npm install

# 后端：Python 虚拟环境 + 依赖
cd backend
python3.11 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
cp .env.example .env   # 填入 OPENAI_API_KEY

# 前端
cd ../frontend
npm install
```

### 2. 开发模式（双端并行）

回到根目录：

```bash
cd ..
npm run dev
```

- 前端：http://localhost:3000
- 后端：http://localhost:8000/docs（FastAPI Swagger）

## 当前进度（M5）

- ✅ 根 monorepo 配置
- ✅ 后端 FastAPI 脚手架（CORS + /api/health）
- ✅ 前端 Next.js + Tailwind + shadcn/ui 脚手架
- ✅ LangGraph + OpenAI 联通（`/api/chat`）
- ✅ 三个工具：`get_weather`（wttr.in）/ `web_search`（SerpAPI）/ `calculate`（sympy）
- ✅ SSE 流式输出（`message_start` / `plan_update` / `step_update` / `content_delta` / `tool_result` / `message_end` / `error`）
- ✅ 多步任务编排：planner 规划 → executor 逐步执行 → aggregator 汇总
- ✅ 前端计划面板 + 工具调用卡片（可展开看参数与结果、显示耗时与失败状态）
- ✅ 记忆持久化：SQLite checkpointer，多会话隔离
- ✅ 前端会话切换（新建 / 切换 / 清空）+ 历史消息加载
- ✅ 错误自动重试：工具层 + LLM 层，指数退避，实时反馈重试进度
- ✅ 暗色模式：跟随系统 / 亮 / 暗 三态切换
- ✅ 空状态引导 + 示例 prompt、头像、流式动画、长消息折叠
- ✅ 自动滚动到底部、单条消息重发
- ✅ 设置页：模型 / 温度 / 重试上限（纯前端，随请求发给后端）

### M3 的执行流程

```
用户提问
  ↓
planner    LLM 生成 2~5 步计划（JSON 强约束）
  ↓
executor   按计划逐个调用工具
  ↓          某步失败 → 标记 skipped，继续下一步
aggregator 汇总所有步骤结果 → 最终答案
```

### M4 的记忆机制

```
/api/chat  {message, thread_id}
  ↓
graph.astream(config={"configurable": {"thread_id": ...}})
  ↓
SqliteSaver 读写 data/checkpoints.db
  ↓
下一轮同 thread_id 时，历史消息自动带入提示词
```

**关键点**：光有 checkpointer 不够 —— planner 和 aggregator 都必须把**历史对话**放进提示词，
否则模型看不到之前聊过什么（"我叫小明"就传不下去）。
这个逻辑在 [text.py](file:///Users/xinao/Desktop/ai-project/agent-tool-assistant/backend/app/agent/text.py) 的 `extract_conversation`。

### 记忆相关接口

| 方法 | 路径 | 说明 |
|---|---|---|
| POST | `/api/chat` | `thread_id` 必传 |
| GET | `/api/memory/{thread_id}` | 读取会话历史消息 |
| DELETE | `/api/memory/{thread_id}` | 清空会话记忆 |
| GET | `/api/threads` | 列出所有会话 |
| GET | `/api/models` | 列出 provider 与可用模型（M6） |

### 工具契约

| 工具 | 入参 | 成功返回 | 失败返回 |
|---|---|---|---|
| `get_weather` | `city` | `{city, temp_c, condition, humidity, wind_kph, observed_at}` | `{error: "city_not_found" \| "timeout" \| "upstream_error"}` |
| `web_search` | `query`, `num=5` | `[{title, snippet, url}]` | `{error: "serpapi_key_missing"}` |
| `calculate` | `expression` | `{result, latex}` | `{error: "forbidden_keyword" \| "syntax_error" \| "evaluation_error"}` |

> `web_search` 需要在 `backend/.env` 填入 `SERPAPI_API_KEY`；未配置时返回错误字典，不会抛异常。

### M5 的错误恢复机制

```
工具/LLM 调用
  ↓
判断错误类型：transient 还是 permanent
  ├── transient（超时 / 限流 / 5xx）→ 指数退避重试 1s → 2s → 4s（最多 3 次）
  │                                  每次重试推送 retry 事件，前端实时显示
  └── permanent（参数非法 / 鉴权失败）→ 立即失败，不重试
  ↓
重试耗尽仍失败 → 步骤标记 failed（红），后续步骤照常执行
```

**关键点 1**：重试判定是白名单式的。只有网络抖动、限流、5xx 才重试；
参数写错、表达式有黑名单词、鉴权失败 —— 重试一万次也是同样的错。

**关键点 2**：三个工具都自己吞掉异常、返回 `{"error": "timeout"}`，
所以重试层要同时判**异常**和**返回值**（`retry_if_exception | retry_if_result`）。

**关键点 3**：`ChatOpenAI(max_retries=0)` 关掉了 openai SDK 的内置重试，
让 tenacity 当唯一的重试层 —— 否则「🔁 重试 N 次」的计数不准。

核心逻辑在 [retry.py](file:///Users/xinao/Desktop/ai-project/agent-tool-assistant/backend/app/agent/retry.py)。

### M5 的步骤状态语义

| 状态 | 含义 | 颜色 | 是否阻塞后续步骤 |
|---|---|---|---|
| `done` | 成功 | 绿 | — |
| `failed` | 执行了但没成功（重试耗尽 / 工具报错） | 红 | ❌ 不阻塞 |
| `skipped` | 根本没法执行（工具不存在 / 参数非法） | 黄 | ❌ 不阻塞 |

### M6 的设置项（纯前端）

设置存 localStorage，随每次请求发给后端：

```
设置页 → lib/settings.ts → POST /api/chat {model?, temperature?, retry_max_attempts?}
  ↓
chat.py 校验后放进 LangGraph 的 configurable
  ↓
nodes.py / retry.py 用 get_config() 取（请求级隔离，不污染全局）
```

| 参数 | 范围 | 说明 |
|---|---|---|
| `model` | 任意模型名 | 不传则用后端 `.env` 的 `OPENAI_MODEL` |
| `temperature` | 0 ~ 1 | 只影响 aggregator；planner 固定 0.2 |
| `retry_max_attempts` | 0 ~ 5 | 不传则用后端 `.env` 的 `RETRY_MAX_ATTEMPTS` |

越界的值会在 API 入口被拒（422），不会流到节点里。

### M6 的模型切换（多 provider）

输入框左边有个模型切换器，可以随时切换 —— 不用去设置页。

模型列表来自后端 `GET /api/models`：后端才知道 `.env` 里配了哪些 key、
各个 provider 下有哪些模型。前端不再硬编码模型名。

| provider | base_url | key 环境变量 | 默认模型 |
|---|---|---|---|
| MiniMax | `OPENAI_BASE_URL` | `OPENAI_API_KEY` | `OPENAI_MODEL` |
| DeepSeek | `DEEPSEEK_BASE_URL` | `DEEPSEEK_API_KEY` | `DEEPSEEK_MODEL` |

**启用 DeepSeek**：在 `backend/.env` 里填上 key，重启后端：

```bash
DEEPSEEK_API_KEY=sk-xxxxxxxx
```

没配 key 的 provider 在前端会置灰，选不了 —— 选了只会得到一个 401。

**路由规则**：模型名以 `deepseek` 开头走 DeepSeek，以 `minimax` 开头走 MiniMax，
其它走默认 provider。核心逻辑在 [providers.py](file:///Users/xinao/Desktop/ai-project/agent-tool-assistant/backend/app/agent/providers.py)。

### M6 的暗色模式

**Tailwind v4 的 `dark:` 默认跟随系统，不能手动切换。**
所以 `globals.css` 里必须加这一行，否则所有 `dark:` 类都是哑弹：

```css
@custom-variant dark (&:is(.dark *));
```

配合 `next-themes` 的 `attribute="class"`，就能用 `.dark` 类驱动了。

## 技术栈

**后端**：Python 3.11 · FastAPI · LangGraph · LangChain OpenAI · httpx · sympy · tenacity
**前端**：Next.js 16 · TypeScript · Tailwind v4 · shadcn/ui · next-themes · lucide-react
