/** Shared types for the M2 SSE chat protocol (see PLAN.md §4 and §8). */

export type Role = "user" | "assistant";

export type ToolCallStatus = "pending" | "running" | "ok" | "failed";

export interface ToolCall {
  id: string;
  name: string;
  args: Record<string, unknown>;
  status: ToolCallStatus;
  result?: unknown;
  error?: string;
  retry?: number;
  latencyMs?: number;
}

export interface TaskStep {
  id: string;
  description: string;
  tool?: string;
  status: "pending" | "running" | "done" | "failed" | "skipped";
}

export interface ChatMessage {
  id: string;
  role: Role;
  text: string;
  toolCalls: ToolCall[];
  plan?: TaskStep[];
  error?: { code: string; message: string };
}

export interface MessageStartEvent {
  id: string;
  role: "assistant";
  thread_id: string;
}

export interface ContentDeltaEvent {
  delta: string;
}

export interface ToolCallEvent {
  id: string;
  name: string;
  args: Record<string, unknown>;
}

export interface ToolResultEvent {
  id: string;
  ok: boolean;
  result?: unknown;
  error?: string;
  retry?: number;
  latency_ms?: number;
}

export interface MessageEndEvent {
  finish_reason: "stop" | "error";
}

export interface ErrorEvent {
  code: string;
  message: string;
  retriable: boolean;
}

/** Union of every event the backend may emit. */
export type ChatEvent =
  | { event: "message_start"; data: MessageStartEvent }
  | { event: "content_delta"; data: ContentDeltaEvent }
  | { event: "tool_call"; data: ToolCallEvent }
  | { event: "tool_result"; data: ToolResultEvent }
  | { event: "plan_update"; data: { plan: TaskStep[] } }
  | { event: "step_update"; data: { id: string; status: TaskStep["status"] } }
  | { event: "message_end"; data: MessageEndEvent }
  | { event: "error"; data: ErrorEvent };
