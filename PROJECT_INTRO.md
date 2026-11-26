# AI Agent 工具调用助手 — 项目介绍

> 面试用项目介绍文档。按「一句话定位 → 背景 → 架构 → 亮点 → 数据 → 踩坑 → 展望」组织，
> 亮点部分遵循「问题 → 方案 → 效果」的写法，方便直接口头复述。

---

## 一、一句话定位

**一个基于 LangGraph 的多步任务编排 Agent**：把用户的一句自然语言请求，自动拆解成 2~5 个可执行步骤，
按计划调用天气查询 / 联网搜索 / 符号计算 / 企业内部文档检索四类工具，再由模型汇总成最终答案；
全过程通过 SSE 流式推送到前端，并具备会话记忆、失败自动重试、多模型热切换能力。

---

## 二、项目背景：要解决什么问题

单轮 Function Calling 的 Demo 大多长这样：模型拿到工具列表，选一个工具、调一次、返回结果。
一旦遇到需要**组合多个能力**的请求（比如"帮我查一下北京天气，再算算今天适合出门的概率阈值"），
或者遇到**外部依赖抖动**（工具超时、模型限流），就暴露出三个问题：

| 问题 | 表现 | 本项目的解法 |
|---|---|---|
| 无规划 | 一步只能做一件事，复杂请求做不完 | planner/executor/aggregator 三节点图编排 |
| 无韧性 | 上游一超时就整链路失败，用户看到白屏 | 分层重试 + 步骤级降级 + 失败语义区分 |
| 无记忆 | 每次对话都是新会话，"我叫小明"传不下去 | Checkpointer 持久化 + 提示词历史注入 |

另外，工程上还有两个长期痛点：**LLM 输出不稳定**（格式飘、参数名瞎编）和**上下文与成本不可控**。

---

## 三、技术栈

| 层 | 选型 | 说明 |
|---|---|---|
| 后端框架 | Python 3.11 · FastAPI | 异步 + 自带 Swagger，天然适合 SSE 长连接 |
| Agent 编排 | LangGraph | 显式状态图 + 条件边 + Checkpointer |
| 模型接入 | LangChain OpenAI 适配器 | 兼容 MiniMax / DeepSeek / OpenAI 官方 |
| 工具协议 | httpx · sympy · SerpAPI | 全异步，自带超时控制 |
| 弹性 | tenacity | 指数退避重试，唯一重试层 |
| 协议 | SSE（sse-starlette） | 后端推事件，前端打字机效果 |
| 前端 | Next.js 16 · React 19 · TypeScript · Tailwind v4 · shadcn/ui | App Router + 组件化 |
| 持久化 | SQLite（AsyncSqliteSaver） | 记忆 checkpointer，零外部依赖 |
| 测试 | pytest · pytest-asyncio | 135 个用例，全部通过 |

---

## 四、系统架构

```
浏览器 (Next.js 16 + shadcn/ui)
   │  POST /api/chat  {message, thread_id, model?, temperature?, retry_max_attempts?}
   │  ← SSE: message_start → plan_update → step_update → tool_result → content_delta → message_end
   ▼
FastAPI (SSE 长连接, CORS, 生命周期管理)
   │
   ▼
LangGraph 图  ── 编译时挂载 SqliteSaver（thread_id 隔离会话）
   │
   START → planner ──→ executor ──→ aggregator → END
             │            ↑ 条件边：还有下一步就回 executor
             │            └── 失败/skipped 不阻塞后续步骤
             └─ JSON 强约束输出 2~5 步计划（temperature 固定 0.2）
   │
   ├─→ 工具层：get_weather / web_search / calculate / search_docs
   │        └─ 全部套 tenacity 重试层（transient 白名单 + 指数退避）
   └─→ LLM 层：planner / aggregator 各自套重试层
```

**一次请求的完整生命周期**

1. 前端把 message + thread_id + 当前设置一起 POST 出去；
2. 后端开 SSE，把 LangGraph 的 `custom` 流事件翻译成前端协议；
3. planner 用 `response_format={"type":"json_object"}` 强约束输出计划，同时做参数名归一化；
4. executor 逐步执行工具，每步前后推 `step_update`，工具回执推 `tool_result`；
5. aggregator 把所有步骤结果 + 历史对话一起交给模型，`astream` 逐 token 推 `content_delta`；
6. 全程任何瞬时失败都会推 `retry` 事件，前端实时显示「正在重试第 N 次」。

---

## 五、核心亮点

### 亮点 1：显式状态图的多步编排 —— 行为可控，而非"让模型自己想办法"

**问题**：让 LLM 自己决定调哪个工具（ReAct 式），行为不可预测、token 消耗大、不好排错。

**方案**：拆成三个职责单一的节点，用 LangGraph 状态图串起来。

- **planner**：只做规划。用 `response_format={"type":"json_object"}` 强约束输出结构化 JSON，
  温度固定 0.2 —— 保证同样的问题拆出同样的步骤。计划上限 5 步，防止模型拆得过碎。
- **executor**：只做执行。**按计划直接调用工具函数，不再让模型二次选择**——快、省 token、行为确定。
  工具调用与 LLM 调用都套在统一的 tenacity 重试层上。
- **aggregator**：只做汇总。把所有步骤结果拼成上下文交给模型，用 `astream` 逐 token 推给前端。

**效果**：每一步的输入输出、耗时、失败原因都可在前端面板展开查看，链路完全可观测。

**工程细节（可讲深度）**：
- planner 输出用**括号配对扫描**抠出最外层 JSON，而不是 `re.findall` —— 模型常带 `<think>` 块和 ```json 围栏，
  简单正则会抓到嵌套对象里的 `{}`；
- **参数名归一化**：实测模型会把 `city` 写成 `location`、`query` 写成 `q`。
  代码里维护了一张别名表（`_ARG_ALIASES`）做纠偏，并按工具 schema 过滤掉模型自创的字段；
- **无计划兜底**：模型没给出可用计划时退化为单步"直接回答"，不会让整条链路空转。

---

### 亮点 2：分层重试 —— 白名单式判定，而不是"捕获所有异常"

**问题**：常见的重试写法是 catch 住所有异常重试三次。结果是参数写错、鉴权失败这类
**再试一万次也是同样的错**的情况白白消耗三倍时间和额度；而真正的网络抖动可能一次就过。

**方案**：在 [retry.py](file:///Users/xinao/Desktop/ai-project/agent-tool-assistant/backend/app/agent/retry.py)
把错误分成三层来判定：

| 层 | 可重试（transient） | 不可重试（permanent） |
|---|---|---|
| LLM 层 | `APITimeoutError`、`APIConnectionError`、`RateLimitError`、`InternalServerError` | `BadRequestError`、`AuthenticationError`、`NotFoundError` |
| 工具层 | `httpx.TimeoutException`、`ConnectError`、`ReadError`、`asyncio.TimeoutError` | `pydantic.ValidationError` |
| 返回值 | `timeout`、`upstream_error`、`upstream_rate_limited`、`rag_timeout`、`rag_unavailable` | `city_not_found`、`forbidden_keyword`、`serpapi_key_missing`、`rag_not_configured` |

判定顺序是**永久错误优先** —— 即使某个异常同时也是 transient 的子类，也一律不重试。

**效果**：指数退避 1s → 2s → 4s，最多 3 次重试（4 次调用）。每次重试通过 SSE 推 `retry` 事件，
前端实时显示「第几次重试、失败原因是什么」，用户不会对着卡住的界面干等。

**三个关键坑（面试官很可能追问）**：

1. **工具失败有两种形态**：抛异常，或者自己吞掉异常返回 `{"error": "timeout"}`。
   四个工具全部选择后者（保证单点失败不炸整条链路），所以重试层必须**同时**判异常和返回值：
   `retry_if_exception(is_transient) | retry_if_result(is_transient_tool_result)`。
2. **不能抛 `RetryError`**：tenacity 默认在重试耗尽时抛 `RetryError`，但工具失败的结果是字典，
   抛异常会把真正的错误码（`timeout`、`city_not_found`）丢掉。改用 `retry_error_callback`
   把最后一次结果原样返回。
3. **必须关掉 SDK 内置重试**：`ChatOpenAI(max_retries=0)`。
   openai SDK 自带 2 次重试，两层叠加会变成 2×4 次调用，而且用户看不到 SDK 内部重试了几次，
   "重试 N 次"的计数就是错的。让 tenacity 当唯一重试层，计数才准确。

---

### 亮点 3：步骤级降级 —— failed / skipped / done 三态语义

**问题**：一个多步任务里，第 2 步失败，要不要把整个计划判死刑？

**方案**：定义三种终态，且**都不阻塞后续步骤**（后续步骤之间通常是独立的）：

| 状态 | 含义 | 触发条件 | 前端颜色 |
|---|---|---|---|
| `done` | 成功 | 工具正常返回 | 绿 |
| `failed` | 执行了但没成功 | 工具报错 / 重试耗尽 | 红 |
| `skipped` | 根本没法执行 | 工具不存在 / 参数非法（`ValidationError`） | 黄 |

**效果**：aggregator 在拼上下文时，把 failed/skipped 的步骤**如实写成"未完成（原因），已跳过"**，
并通过提示词明确要求"不要编造结果"。所以模型不会在天气查询失败后编一个温度出来。

---

### 亮点 4：会话级记忆 —— Checkpointer + 提示词历史注入

**问题**：LangGraph 挂了 Checkpointer，模型还是"失忆"。

**根因**：这是很多人踩的坑 —— **光有 checkpointer 不够**。checkpointer 负责把状态存下来，
但如果 planner / aggregator 的提示词里只塞了当前这一轮的问题，模型根本看不到之前聊过什么。
用户说"我叫小明"，下一句问"我叫什么"，模型照样答不上来。

**方案**：两件事必须同时做。

1. **持久化**：`AsyncSqliteSaver` + `thread_id`。图在编译时挂上 checkpointer，
   调用时通过 `config={"configurable": {"thread_id": ...}}` 指定会话，不同会话状态互相隔离。
2. **提示词注入**：[text.py](file:///Users/xinao/Desktop/ai-project/agent-tool-assistant/backend/app/agent/text.py)
   的 `extract_conversation` 把消息列表拆成 `(当前问题, 历史对话)`，
   历史对话转成 OpenAI 格式后**插到系统提示词和当前问题之间**：

   ```
   [system: PLANNER_PROMPT] → [user: 我叫小明] → [assistant: 你好小明] → [user: 我叫什么？]
   ```

**细节**：函数会主动把最后一条用户消息从历史里摘掉，避免和"当前问题"重复。

**工程细节**：`AsyncSqliteSaver.from_conn_string` 是个 async context manager，用完连接就断了。
所以自己用 `aiosqlite` 建立连接再包一层，让连接在整个应用生命周期内保持打开，
并在 FastAPI 的 `lifespan` 里统一创建和释放。

---

### 亮点 5：RAG 接入 —— 只取 chunk，不生成答案

**问题**：接外部 RAG 服务时，用它自带的"检索 + 生成"接口，还是只用检索接口？

**方案**：**只用检索**。`search_docs` 调 RAG 服务的 `POST /api/search`，拿回**原文片段**
（source / page / text / similarity / doc_id），由本 Agent 自己的 LLM 组织答案。

**为什么**：走"检索 + 生成"等于跑两次 LLM —— 成本翻倍、延迟叠加；
而且拿到的已经是二手答案，没法溯源到原文。只做检索则保留了原文片段，
最终答案可回溯到具体文档页码，前端还能把每条片段的来源、页码、相似度单独展示。

**另一个关键点**：planner 的提示词里明确区分了 `search_docs`（内部文档）和 `web_search`（互联网公开信息）。
不区分的话，问"金额字段该用什么类型"会跑去网上搜数据库规范，而不是查公司自己的 PRD。

**防护**：单 chunk 文本截断到 1500 字符、`top_k` 钳制在 1~10、查询词为空直接返回
`empty_query` 而不是把空查询打到下游。

---

### 亮点 6：多 Provider 路由 + 请求级配置隔离

**问题**：想支持多个模型服务商时踩了个坑 —— 前端能切模型名，但后端只有一个全局
`OPENAI_BASE_URL`。切到 `gpt-4o` 时 base_url 还指着 MiniMax，上游直接报 `unknown model`。

**方案**：**模型名 → provider 的路由表**（[providers.py](file:///Users/xinao/Desktop/ai-project/agent-tool-assistant/backend/app/agent/providers.py)）：

| provider | 路由规则 | base_url | key 环境变量 |
|---|---|---|---|
| MiniMax | 模型名以 `minimax` 开头 | `OPENAI_BASE_URL` | `OPENAI_API_KEY` |
| DeepSeek | 模型名以 `deepseek` 开头 | `DEEPSEEK_BASE_URL` | `DEEPSEEK_API_KEY` |
| OpenAI 官方 | 其余 | 空（官方地址） | `OPENAI_API_KEY` |

DeepSeek 也是 OpenAI 兼容格式，本质只是换了 `base_url` 和 `key`。

**另一个设计原则**：**模型列表由后端 `/api/models` 提供，前端不硬编码**。
因为"配没配 key""有哪些模型"是后端状态，前端硬编码一份迟早和 `.env` 对不上。
没配 key 的 provider 在前端直接置灰，选不了 —— 选了也只会得到一个 401。

**请求级配置隔离**：设置页的模型 / 温度 / 重试上限**不修改后端全局配置**，
而是随请求塞进 LangGraph 的 `configurable`，节点里用 `get_config()` 取。
这样每次请求独立生效，改一次设置不会污染其他会话，也不会让并发请求互相干扰。

**温度的差异化处理**：**planner 固定 0.2**（规划要稳定，同样的问题拆出同样的步骤），
**aggregator 用请求里的值**（汇总要发散，写最终回答）。

---

### 亮点 7：全链路 SSE 与事件协议 —— 过程可见

**问题**：Agent 跑一个多步任务可能十几秒。前端如果只等一个最终 JSON，用户面对的就是一个转圈。

**方案**：定义了一套 9 类事件的 SSE 协议，后端把 LangGraph 的 `custom` 流翻译成这套协议：

| 事件 | 时机 | 载荷 |
|---|---|---|
| `message_start` | 助手消息开始 | id, role, thread_id |
| `plan_update` | 计划生成完毕 | 完整步骤列表 |
| `step_update` | 单步状态切换 | id, status, error, retry |
| `tool_result` | 工具执行回执 | name, args, ok, result/error, retry, latency_ms |
| `retry` | 即将重试 | layer(tool/llm), stage, attempt, max_attempts, message |
| `content_delta` | 正文片段 | delta |
| `message_end` | 结束 | finish_reason(stop/error) |
| `error` | 全局错误 | code, message, retriable |

**为什么不用 LangGraph 内置的 `messages` 流模式**：那个模式会把 planner 输出的 JSON 也当成正文推给前端。
本项目的正文只来自 aggregator，所以在节点内部自己 `astream` 更可控。

**前端配套**：计划面板（实时显示每步状态圆点）、工具调用卡片（可展开看参数、结果、耗时、重试次数）、
RAG 片段列表（来源 + 页码 + 相似度）、重试中的实时提示。

---

### 亮点 8：工程化细节

- **工具契约化**：四个工具全部遵循「成功返回业务字段 / 失败返回 `{"error": "<错误码>"}`」，
  错误码是可枚举的语义化字符串，前端和测试都依赖它。
- **计算器双防线**：[calculator.py](file:///Users/xinao/Desktop/ai-project/agent-tool-assistant/backend/app/agent/tools/calculator.py)
  黑名单预过滤（`__`、`import`、`exec(`、`os`、`sys`、`;`、换行等，且先转小写所以 `IMPORT` 也拦得住）
  **+** sympy 求值时通过 `locals=SAFE_NAMESPACE` 白名单限定只能看到十几个数学符号。两道防线缺一不可。
- **错误信息面向用户**：上游报 `unknown model 'gpt-4o-mini'`，直接甩给用户毫无意义。
  `_friendly_error` 把它翻译成「模型不可用，请到设置页确认模型名是否正确」。
  同时区分 transient（`retriable=true`，重发可能好）和 permanent（`retriable=false`，重发没用）。
- **推理块过滤**：[text.py](file:///Users/xinao/Desktop/ai-project/agent-tool-assistant/backend/app/agent/text.py)
  的 `ThinkFilter` 处理 MiniMax 这类模型会把 `<think>` 推理混在正文里输出的情况。
  难点是**标签会跨 chunk 断裂**（可能先来 `...<thi` 再来 `nk>...`），
  所以要把"可能是标签前缀"的尾巴扣住，等下一个 chunk 再判断。
- **耗时统计是横切关注点**：用 `_with_latency` 包装每个工具，一行不改就拿到耗时；
  SSE 层再把 `_latency_ms` 摘掉，因为它不属于工具的业务结果。
- **提示词格式约束**：evaluator 脚本跑下来发现模型输出格式五花八门（有的加粗、有的用 LaTeX、
  有的加千分位逗号、开头带空行），于是把格式约定写进聚合器提示词，前端渲染才稳定。

---

## 六、量化数据

| 指标 | 数值 |
|---|---|
| 后端业务代码 | 2410 行 |
| 后端测试代码 | 1648 行（测试/业务 ≈ 0.68） |
| 前端代码 | 3071 行 / 29 个 TS/TSX 文件 |
| 代码总量 | 7129 行 |
| 测试用例 | 135 个，全部通过，1.74s |
| 工具数量 | 4 个（天气 / 搜索 / 计算 / RAG） |
| SSE 事件类型 | 9 类 |
| 里程碑 | M1~M6 六个阶段 + RAG 附加特性 |
| Git 提交 | 6 次（按里程碑划分） |

---

## 七、踩过的坑（挑最有说服力的讲）

1. **SSE 在浏览器里一片空白，curl 却正常** —— `sse-starlette` 发的是 CRLF（`\r\n\r\n`），
   前端按 `\n\n` 切帧就切不开。前端统一做 `buffer.replace(/\r\n/g, "\n")` 归一化后才解决。
2. **暗色模式所有 `dark:` 类都是哑弹** —— Tailwind v4 的 `dark:` 默认跟随系统、无法手动切换。
   必须加 `@custom-variant dark (&:is(.dark *));` 配合 `next-themes` 的 `attribute="class"`。
3. **流式事件覆盖** —— `get_stream_writer()` 传出去的是引用，后面改 step 字段会同步改到已发出的那份，
   消费端看到的是被覆盖后的状态（曾出现 `running` 直接变成 `done`）。解法是推送时传 `dict(step)` 副本。
4. **`top_k or 5` 的陷阱** —— 这样写 `top_k=0` 会被当成"没传"，结果变成 5 而不是钳到下限 1。
5. **重试次数统计不准** —— SDK 内置重试和 tenacity 叠加，实际调用了 8 次但界面显示 3 次。
   关掉 `max_retries=0` 后才准。
6. **聚合器流式输出不能重试** —— 已经吐过正文后再重试，前端会收到重复内容。
   所以 aggregator 的重试只在"还没吐出第一个字"时生效，一旦开流就直接失败。

---

## 八、后续可扩展方向

- **并行执行**：目前步骤是串行的，无依赖关系的步骤（比如"查天气"和"查新闻"）可以并发，
  在 executor 里用 `asyncio.gather` 编排，延迟直接砍半。
- **人机确认（Human-in-the-loop）**：LangGraph 支持在节点前后挂起等人工确认，
  适合"发送邮件""下单"这类有副作用的动作加一道人工闸门。
- **向量库下沉**：现在 RAG 是外部服务，可以把检索改为内置向量库 + 增量索引，
  减少一次网络往返。
- **可观测性**：接 OpenTelemetry，把每一步的 LLM token 消耗、工具延迟、检索命中率全链路打点，
  用于成本优化和效果回归。
- **评测集化**：把 `eval_format.py` 扩成带标准答案的回归集，对 planner 的拆解准确率做量化评估。

---

## 九、面试时怎么讲（原则建议）

1. **先说问题，再说方案**。每个亮点都从"这里有个什么问题"开始，比罗列技术栈可信得多。
2. **数字要准**。135 个测试、7129 行代码、4 个工具、9 类事件 —— 报准了经得起追问，报错了很减分。
3. **主动交代取舍**。比如"串行执行是为了保证步骤顺序，牺牲了并行收益"，
   比被问出来强得多。
4. **每个亮点准备一个"如果重做我会怎么改"**。这是区分"做过"和"做懂了"的关键。
5. **代码位置随手可指**。本介绍里的所有能力都有对应文件和函数，
   追问时可以直接定位到行。
