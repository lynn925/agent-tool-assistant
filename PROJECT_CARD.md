# 面试速查卡（单页 · 打印用）

> 面试前 5 分钟扫一遍。所有内容都能在代码里定位到行。

---

## 一、30 秒电梯陈述

> 基于 **LangGraph** 的多步任务编排 Agent。把一句自然语言请求拆成 2~5 步，
> 按计划调 4 类工具（天气 / 搜索 / 计算 / RAG），再由模型汇总成答案。
> 全程 **SSE 流式**推送，支持**会话记忆**、**分层重试**、**多模型热切换**。
> 7129 行代码 · 135 个测试全绿。

---

## 二、四个亮点（讲全这四个就够）

### ① 分层重试 —— 白名单判定

**问题**：catch 所有异常重试三次 → 参数错误也重试（白耗额度），真抖动可能一次就过。

**方案**：
| 类别 | 例子 | 动作 |
|---|---|---|
| transient | 超时 / 连接失败 / 限流 / 5xx | 指数退避 1s→2s→4s，最多 3 次 |
| permanent | 参数非法 / 鉴权失败 / 模型不存在 | 立即失败，**不重试** |

判定顺序：**永久错误优先**（哪怕也是 transient 子类也不重试）。

**三个坑**：
1. 工具**吞异常返回字典** → 判定要 `retry_if_exception(...) | retry_if_result(...)`
2. tenacity 抛 `RetryError` 会**丢错误码** → 用 `retry_error_callback` 原样返回
3. openai SDK **自带 2 次重试** → 必须 `max_retries=0`，让 tenacity 当唯一重试层

→ [retry.py](file:///Users/xinao/Desktop/ai-project/agent-tool-assistant/backend/app/agent/retry.py)

---

### ② 会话记忆 —— Checkpointer ≠ 有记忆

**反直觉点**：挂上 Checkpointer **模型依然失忆**。
Checkpointer 只负责**存状态**，历史**不会自动进提示词**。

**必须两件事同时做**：
1. 持久化：`AsyncSqliteSaver` + `thread_id` 隔离会话
2. 提示词注入：`extract_conversation` 拆成 `(当前问题, 历史对话)`，
   历史插到 system prompt 和当前问题**中间**

→ [text.py](file:///Users/xinao/Desktop/ai-project/agent-tool-assistant/backend/app/agent/text.py)

---

### ③ 步骤级降级 —— 三态语义

| 状态 | 含义 | 触发 | 颜色 |
|---|---|---|---|
| `done` | 成功 | 正常返回 | 绿 |
| `failed` | 执行了没成功 | 工具报错 / 重试耗尽 | 红 |
| `skipped` | 没法执行 | 工具不存在 / 参数非法 | 黄 |

**都不阻塞后续步骤**；aggregator 把失败**如实写成"未完成（原因）"**，
提示词明确要求**不要编造结果**。

---

### ④ RAG —— 只取 chunk 不生成

- 用**纯检索**接口（`POST /api/search`），不用"检索+生成"
- 理由：跑两次 LLM → **成本翻倍、延迟叠加**；二手答案**无法溯源**
- 拿到原文片段（source/page/similarity）→ 最终答案可回溯到页码
- 提示词区分 `search_docs`（内部文档）vs `web_search`（互联网）
  ——否则问"金额字段用什么类型"会去搜数据库规范，而不是查公司 PRD

---

## 三、架构一句话

```
前端 Next.js 16 → POST /api/chat (SSE) → FastAPI → LangGraph 图
   START → planner (JSON 强约束, T=0.2) → executor (循环, 失败不阻塞)
   → aggregator (astream 逐 token) → END
   工具层 / LLM 层 各套 tenacity 重试
   编译时挂 SqliteSaver（thread_id 隔离）
```

**关键设计**：executor **按计划直接调工具，不让模型二次选** —— 快、省 token、行为确定。
代价：灵活性差，靠 planner 规划质量兜底。

---

## 四、必须说准的数字

| 项 | 数 |
|---|---|
| 代码总量 | **7129** 行 |
| 后端业务 / 测试 | 2410 / 1648 |
| 前端 | 3071（29 个 TS/TSX） |
| 测试用例 | **135**，全通过，1.74s |
| 工具 / SSE 事件 | **4** 个 / **9** 类 |
| 里程碑 | M1~M6 + RAG 附加 |

**测试分布**（追问时报得出更可信）：
retry 34 · providers 16 · tools 15 · rag 15 · nodes 15 · nodes_retry 13 · settings 11 · memory 8 · sse 6 · health 2

---

## 五、三个必说的坑

1. **SSE 在浏览器一片空白，curl 正常** → `sse-starlette` 发 CRLF，前端按 `\n\n` 切不开
   → 统一 `buffer.replace(/\r\n/g, "\n")` 归一化
2. **Tailwind v4 暗色模式全是哑弹** → `dark:` 默认跟随系统
   → 必加 `@custom-variant dark (&:is(.dark *));` + `next-themes` 的 `attribute="class"`
3. **流式事件状态被覆盖** → `get_stream_writer()` 传**引用**，改 step 会同步改已发出的那份
   → 推送时传 `dict(step)` 副本（有回归测试锁住）

**备选坑**：`top_k or 5` 会把 0 当成"没传" · SDK 重试叠加导致计数不准 · aggregator 开流后不能重试（会重复内容）

---

## 六、被追问时直接指代码

| 能力 | 位置 |
|---|---|
| 重试策略 | [retry.py](file:///Users/xinao/Desktop/ai-project/agent-tool-assistant/backend/app/agent/retry.py) |
| 编排三节点 | [nodes.py](file:///Users/xinao/Desktop/ai-project/agent-tool-assistant/backend/app/agent/nodes.py) |
| 记忆注入 / 推理过滤 | [text.py](file:///Users/xinao/Desktop/ai-project/agent-tool-assistant/backend/app/agent/text.py) |
| SSE 事件翻译 | [chat.py](file:///Users/xinao/Desktop/ai-project/agent-tool-assistant/backend/app/api/chat.py) |
| Provider 路由 | [providers.py](file:///Users/xinao/Desktop/ai-project/agent-tool-assistant/backend/app/agent/providers.py) |
| RAG 工具 | [tools/rag.py](file:///Users/xinao/Desktop/ai-project/agent-tool-assistant/backend/app/agent/tools/rag.py) |
| 计算器双防线 | [tools/calculator.py](file:///Users/xinao/Desktop/ai-project/agent-tool-assistant/backend/app/agent/tools/calculator.py) |
| 前端 SSE 解析 | [lib/api.ts](file:///Users/xinao/Desktop/ai-project/agent-tool-assistant/frontend/lib/api.ts) |

---

## 七、别说错的话

- ❌ "我们团队用了…" → **个人项目**
- ❌ "性能提升 XX%" → **没有压测数据**，讲设计收益不讲性能百分比
- ❌ "用了最前沿框架" → 不吹框架，讲**自己解决的具体问题**
- ❌ "Checkpointer 实现了记忆" → 说清"**必须自己注入提示词**"才有分量

---

## 八、下一步（被问"还能怎么改"）

1. **并行执行** —— 无依赖步骤用 `asyncio.gather`，延迟砍半（当前严格串行是**主动取舍**）
2. **Human-in-the-loop** —— 有副作用的动作加人工闸门
3. **共享 httpx 连接池** —— 工具现在每次新建 client，连接池完全没用上
4. **换 Postgres checkpointer** —— SQLite 不支持多实例
5. **评测集化** —— `eval_format.py` 扩成带标准答案的回归集，量化 planner 准确率
