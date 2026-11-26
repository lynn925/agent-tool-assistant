/**
 * M2 SSE 事件协议的前端类型定义。
 *
 * 建议先读这个文件 —— 看完就知道后端会发哪些事件、
 * 每种事件带什么数据、前端要怎么处理。
 *
 * 对应后端：backend/app/api/chat.py
 * 协议出处：PLAN.md §4（事件）与 §8（前端类型）
 */

/**
 * 工具名 → 中文显示名。
 *
 * 放在这里而不是各组件内部 —— 之前 PlanPanel 和 ToolCallCard
 * 各有一份，加新工具时漏改一处就导致标签不一致。
 */
export const TOOL_LABELS: Record<string, string> = {
  get_weather: "查询天气",
  web_search: "联网搜索",
  calculate: "计算器",
  search_docs: "文档检索",
};

/** 消息角色：用户或助手 */
export type Role = "user" | "assistant";

/**
 * 工具调用的四种状态。
 * pending 等待中 → running 执行中 → ok 成功 / failed 失败
 */
export type ToolCallStatus = "pending" | "running" | "ok" | "failed";

/** 一次工具调用（前端内部状态） */
export interface ToolCall {
  /** 工具调用 ID，由模型生成，用于和 tool_result 事件配对 */
  id: string;
  /** 工具名：get_weather / web_search / calculate */
  name: string;
  /** 调用参数 */
  args: Record<string, unknown>;
  /** 当前状态 */
  status: ToolCallStatus;
  /** 执行结果（成功时） */
  result?: unknown;
  /** 错误码（失败时），如 city_not_found */
  error?: string;
  /** 重试次数（M5 用，M2 恒为 0） */
  retry?: number;
  /** 执行耗时（毫秒） */
  latencyMs?: number;
}

/** 任务步骤（M3 多步编排） */
export interface TaskStep {
  id: string;
  /** 中文描述 */
  description: string;
  /** 要用的工具名，没有则为空 */
  tool?: string;
  /** 调用参数 */
  args?: Record<string, unknown>;
  status: "pending" | "running" | "done" | "failed" | "skipped";
  /** 执行结果（成功时） */
  result?: unknown;
  /** 错误码（失败时） */
  error?: string | null;
  /** M5：这步重试了几次 */
  retry?: number;
}

/** 一条聊天消息（前端渲染用） */
export interface ChatMessage {
  id: string;
  role: Role;
  /** 消息正文 */
  text: string;
  /** 这条消息关联的工具调用列表 */
  toolCalls: ToolCall[];
  /** 任务计划（M3 用） */
  plan?: TaskStep[];
  /** 错误信息 */
  error?: { code: string; message: string };
}

// ---------------------------------------------------------------------------
// 以下是后端会发来的各种事件的数据结构
// ---------------------------------------------------------------------------

/** message_start：一条助手消息开始 */
export interface MessageStartEvent {
  /** 消息 ID */
  id: string;
  role: "assistant";
  /** 会话 ID，M4 起用于记忆持久化 */
  thread_id: string;
}

/** content_delta：文本片段 */
export interface ContentDeltaEvent {
  /** 增量文本，拼接到消息末尾 */
  delta: string;
}

/** tool_call：模型决定调用某个工具 */
export interface ToolCallEvent {
  id: string;
  name: string;
  args: Record<string, unknown>;
}

/** tool_result：工具执行完毕的回执 */
export interface ToolResultEvent {
  /** 对应的步骤 ID（M3 里是 step-1 这样的步骤号） */
  id: string;
  /** 工具名 */
  name: string;
  /** 调用参数 */
  args: Record<string, unknown>;
  /** 是否成功 */
  ok: boolean;
  /** 结果数据（成功时） */
  result?: unknown;
  /** 错误码（失败时） */
  error?: string | null;
  /** 重试次数（M5）：重试几次后成功/失败 */
  retry?: number;
  /** 执行耗时（毫秒） */
  latency_ms?: number;
}

/**
 * retry：M5 的重试事件。
 *
 * 每次「即将重试」时推一次，让前端实时显示「重试中…」而不是干等。
 */
export interface RetryEvent {
  /** 出错的层：tool 工具层 / llm 模型层 */
  layer: "tool" | "llm";
  /** 哪一步：工具层是 step-1，模型层是 planner / aggregator */
  stage: string;
  /** 工具名（只有工具层有） */
  name?: string;
  /** 即将进行的第几次重试，从 1 开始 */
  attempt: number;
  /** 总共最多尝试几次（含首次） */
  max_attempts: number;
  /** 失败原因 */
  message: string;
}

/** message_end：助手消息结束 */
export interface MessageEndEvent {
  finish_reason: "stop" | "error";
}

/** error：全局错误 */
export interface ErrorEvent {
  code: string;
  message: string;
  /** 是否可以重试 */
  retriable: boolean;
}

/** plan_update：M3 的完整任务计划 */
export interface PlanUpdateEvent {
  plan: TaskStep[];
}

/** step_update：M3 的单步状态切换 */
export interface StepUpdateEvent {
  id: string;
  status: TaskStep["status"];
  description: string;
  tool?: string | null;
  /** M5：失败原因（failed / skipped 时有值） */
  error?: string | null;
  /** M5：这步重试了几次 */
  retry?: number;
}

/**
 * 后端可能发来的全部事件类型。
 *
 * M3 新增了 plan_update / step_update 两个计划相关事件。
 * M5 新增了 retry 事件（重试中的实时提示）。
 */
export type ChatEvent =
  | { event: "message_start"; data: MessageStartEvent }
  | { event: "content_delta"; data: ContentDeltaEvent }
  | { event: "tool_call"; data: ToolCallEvent }
  | { event: "tool_result"; data: ToolResultEvent }
  | { event: "plan_update"; data: PlanUpdateEvent }
  | { event: "step_update"; data: StepUpdateEvent }
  | { event: "retry"; data: RetryEvent }
  | { event: "message_end"; data: MessageEndEvent }
  | { event: "error"; data: ErrorEvent };
