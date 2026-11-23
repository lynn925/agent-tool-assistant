/**
 * 与后端 FastAPI 通信的封装。
 *
 * M2 的核心是 chatStream —— 负责把 SSE 流解析成一个个事件回调给调用方。
 */

import type { ChatEvent } from "@/lib/types";

/** 后端地址，在 frontend/.env 里用 NEXT_PUBLIC_BACKEND_URL 配置 */
const BACKEND_URL =
  process.env.NEXT_PUBLIC_BACKEND_URL ?? "http://localhost:8000";

/** 带 HTTP 状态码的错误 */
export class ApiError extends Error {
  constructor(public status: number, message: string) {
    super(message);
  }
}

/** 发送普通 JSON 请求并解析响应 */
async function request<T>(path: string, init?: RequestInit): Promise<T> {
  const res = await fetch(`${BACKEND_URL}${path}`, {
    ...init,
    headers: {
      "Content-Type": "application/json",
      ...(init?.headers ?? {}),
    },
  });
  if (!res.ok) {
    const text = await res.text().catch(() => res.statusText);
    throw new ApiError(res.status, text);
  }
  return res.json() as Promise<T>;
}

// ---------------------------------------------------------------------------
// M1 的接口
// ---------------------------------------------------------------------------

export interface EchoResponse {
  reply: string;
}

/** 回显接口（调试用） */
export async function echo(message: string): Promise<EchoResponse> {
  return request<EchoResponse>("/api/echo", {
    method: "POST",
    body: JSON.stringify({ message }),
  });
}

/** 健康检查 */
export async function health(): Promise<{ status: string }> {
  return request<{ status: string }>("/api/health");
}

// ---------------------------------------------------------------------------
// M2 的聊天接口（SSE）
// ---------------------------------------------------------------------------

export interface ChatHandlers {
  /** 每收到一个事件就回调一次 */
  onEvent: (event: ChatEvent) => void;
  /** 中止信号，配合 AbortController 实现"停止"按钮 */
  signal?: AbortSignal;
}

/**
 * 调用 /api/chat 并消费 SSE 流。
 *
 * 流程：
 *   1. POST 发起请求，拿回 response.body 流；
 *   2. 用 getReader() 逐块读取，累积到 buffer；
 *   3. 按空行切成一帧帧，解析成事件后回调 onEvent。
 */
export async function chatStream(
  message: string,
  threadId: string,
  { onEvent, signal }: ChatHandlers,
): Promise<void> {
  const res = await fetch(`${BACKEND_URL}/api/chat`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ message, thread_id: threadId }),
    signal,
  });

  if (!res.ok || !res.body) {
    const text = await res.text().catch(() => res.statusText);
    throw new ApiError(res.status, text);
  }

  const reader = res.body.getReader();
  const decoder = new TextDecoder();
  let buffer = "";

  while (true) {
    const { done, value } = await reader.read();
    if (done) break;

    buffer += decoder.decode(value, { stream: true });

    // SSE 用空行分帧。服务端（sse-starlette）发的是 CRLF (\r\n\r\n)，
    // 所以必须先归一化成 LF 再切帧 —— 这是 M2 踩过的一个坑：
    // 不做归一化的话，curl 能看到完整内容但浏览器里一片空白。
    buffer = buffer.replace(/\r\n/g, "\n");
    let separator = buffer.indexOf("\n\n");
    while (separator !== -1) {
      const frame = buffer.slice(0, separator);
      buffer = buffer.slice(separator + 2);
      const parsed = parseFrame(frame);
      if (parsed) onEvent(parsed);
      separator = buffer.indexOf("\n\n");
    }
  }
}

/**
 * 解析单帧 SSE。
 *
 * 一帧长这样：
 *   event: content_delta
 *   data: {"delta": "你好"}
 *
 * 返回 null 表示这一帧不是有效事件（比如注释行或心跳）。
 */
function parseFrame(frame: string): ChatEvent | null {
  let eventName = "";
  const dataLines: string[] = [];

  for (const rawLine of frame.split("\n")) {
    // 兼容可能残留的 \r
    const line = rawLine.endsWith("\r") ? rawLine.slice(0, -1) : rawLine;
    if (line.startsWith("event:")) {
      eventName = line.slice(6).trim();
    } else if (line.startsWith("data:")) {
      dataLines.push(line.slice(5).trim());
    }
  }

  if (!eventName || dataLines.length === 0) return null;

  try {
    return {
      event: eventName,
      data: JSON.parse(dataLines.join("\n")),
    } as ChatEvent;
  } catch {
    // JSON 解析失败就丢掉这一帧，不影响后续
    return null;
  }
}

// ---------------------------------------------------------------------------
// M4 记忆接口
// ---------------------------------------------------------------------------

/** 后端保存的历史消息 */
export interface HistoryMessage {
  role: "user" | "assistant";
  text: string;
}

/** 会话摘要信息 */
export interface ThreadInfo {
  thread_id: string;
  /** 最后活跃时间（ISO 8601） */
  updated_at: string | null;
  /** 消息条数 */
  message_count: number;
}

/** 读取某个会话的历史消息 */
export async function getMemory(
  threadId: string,
): Promise<{ thread_id: string; messages: HistoryMessage[] }> {
  return request(`/api/memory/${encodeURIComponent(threadId)}`);
}

/** 清空某个会话的记忆 */
export async function clearMemory(
  threadId: string,
): Promise<{ thread_id: string; cleared: boolean }> {
  return request(`/api/memory/${encodeURIComponent(threadId)}`, {
    method: "DELETE",
  });
}

/** 列出所有会话 */
export async function listThreads(): Promise<{ threads: ThreadInfo[] }> {
  return request("/api/threads");
}
