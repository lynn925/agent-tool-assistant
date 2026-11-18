# AI Agent 工具调用助手

渐进式 AI Agent 项目，6 个里程碑逐步搭建：

| M | 目标 | 状态 |
|---|---|---|
| M1 | 脚手架（FastAPI + Next.js + LangGraph） | ✅ 已完成 |
| M2 | OpenAI Function Calling 三工具（天气/搜索/计算器） | ✅ 已完成 |
| M3 | LangGraph 多步任务编排 | ⏳ |
| M4 | 记忆（Checkpointer） | ⏳ |
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

## 当前进度（M2）

- ✅ 根 monorepo 配置
- ✅ 后端 FastAPI 脚手架（CORS + /api/health）
- ✅ 前端 Next.js + Tailwind + shadcn/ui 脚手架
- ✅ LangGraph + OpenAI 联通（`/api/chat`）
- ✅ 三个工具：`get_weather`（wttr.in）/ `web_search`（SerpAPI）/ `calculate`（sympy）
- ✅ SSE 流式输出（`message_start` / `content_delta` / `tool_call` / `tool_result` / `message_end` / `error`）
- ✅ 前端工具调用卡片（可展开看参数与结果、显示耗时与失败状态）
- ⏳ M3 起做多步任务编排

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
