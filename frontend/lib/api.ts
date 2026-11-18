/** Tiny fetch wrapper that talks to the FastAPI backend. */

import type { ChatEvent } from "@/lib/types";

const BACKEND_URL =
  process.env.NEXT_PUBLIC_BACKEND_URL ?? "http://localhost:8000";

export class ApiError extends Error {
  constructor(public status: number, message: string) {
    super(message);
  }
}

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

// M1 endpoints ------------------------------------------------------------

export interface EchoResponse {
  reply: string;
}

export async function echo(message: string): Promise<EchoResponse> {
  return request<EchoResponse>("/api/echo", {
    method: "POST",
    body: JSON.stringify({ message }),
  });
}

export async function health(): Promise<{ status: string }> {
  return request<{ status: string }>("/api/health");
}

// M2 chat (SSE) -----------------------------------------------------------

export interface ChatHandlers {
  onEvent: (event: ChatEvent) => void;
  signal?: AbortSignal;
}

/**
 * POST /api/chat and consume the SSE stream.
 * Parses the `event:`/`data:` pairs emitted by the FastAPI backend.
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

    // SSE frames are separated by a blank line. The server may use CRLF,
    // so normalise before splitting.
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

function parseFrame(frame: string): ChatEvent | null {
  let eventName = "";
  const dataLines: string[] = [];

  for (const rawLine of frame.split("\n")) {
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
    return null;
  }
}
