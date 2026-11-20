# Backend — FastAPI + LangGraph

## 启动

```bash
python3.11 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
cp .env.example .env   # 填 OPENAI_API_KEY

uvicorn app.main:app --reload --host 0.0.0.0 --port 8000
```

- Swagger UI：http://localhost:8000/docs
- 健康检查：http://localhost:8000/api/health

## 目录

```
app/
├── main.py          # FastAPI 入口、CORS
├── config.py        # Settings (env)
├── api/
│   ├── health.py    # /api/health
│   ├── echo.py      # /api/echo（调试用）
│   └── chat.py      # /api/chat（SSE）
├── agent/
│   ├── state.py     # AgentState + TaskStep
│   ├── prompts.py   # planner / aggregator 提示词
│   ├── nodes.py     # planner / executor / aggregator
│   ├── text.py      # ThinkFilter（剥离推理块）
│   ├── graph.py     # M3 图结构
│   └── tools/
│       ├── weather.py    # get_weather(city)
│       ├── search.py     # web_search(query, num)
│       └── calculator.py # calculate(expression)
└── tests/
```

## 当前里程碑

- **M1**：FastAPI 骨架 + CORS + /api/health + /api/echo
- **M2**：三工具（天气/搜索/计算器）+ `bind_tools`/`ToolNode` + SSE 流式
- **M3**：多步任务编排（planner → executor → aggregator）+ 计划面板
- M4 起做记忆持久化
