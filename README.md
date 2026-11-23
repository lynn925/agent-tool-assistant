# AI Agent 工具调用助手

渐进式 AI Agent 项目，6 个里程碑逐步搭建：

| M | 目标 | 状态 |
|---|---|---|
| M1 | 脚手架（FastAPI + Next.js + LangGraph） | ✅ 已完成 |
| M2 | OpenAI Function Calling 三工具（天气/搜索/计算器） | ✅ 已完成 |
| M3 | LangGraph 多步任务编排 | ✅ 已完成 |
| M4 | 记忆（Checkpointer） | ✅ 已完成 |
| M5 | 错误恢复（重试） | ⏳ |
| M6 | UI 完善 + 部署文档 | ⏳ |

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

## 当前进度（M4）

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
- ⏳ M5 起做错误恢复

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

### 工具契约

| 工具 | 入参 | 成功返回 | 失败返回 |
|---|---|---|---|
| `get_weather` | `city` | `{city, temp_c, condition, humidity, wind_kph, observed_at}` | `{error: "city_not_found" \| "timeout" \| "upstream_error"}` |
| `web_search` | `query`, `num=5` | `[{title, snippet, url}]` | `{error: "serpapi_key_missing"}` |
| `calculate` | `expression` | `{result, latex}` | `{error: "forbidden_keyword" \| "syntax_error" \| "evaluation_error"}` |

> `web_search` 需要在 `backend/.env` 填入 `SERPAPI_API_KEY`；未配置时返回错误字典，不会抛异常。

## 技术栈

**后端**：Python 3.11 · FastAPI · LangGraph · LangChain OpenAI · httpx · sympy
**前端**：Next.js 16 · TypeScript · Tailwind v4 · shadcn/ui
