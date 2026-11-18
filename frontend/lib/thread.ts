/**
 * localStorage-backed thread_id manager for the chat session.
 * M4 will use this id as LangGraph's `configurable.thread_id` for memory.
 */

const KEY = "agent.thread_id";

export function getThreadId(): string {
  if (typeof window === "undefined") return "ssr";
  let id = window.localStorage.getItem(KEY);
  if (!id) {
    id = crypto.randomUUID();
    window.localStorage.setItem(KEY, id);
  }
  return id;
}

export function resetThreadId(): string {
  const id = crypto.randomUUID();
  if (typeof window !== "undefined") {
    window.localStorage.setItem(KEY, id);
  }
  return id;
}