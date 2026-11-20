/**
 * 基于 localStorage 的会话 ID（thread_id）管理。
 *
 * M2 只是把这个 ID 传给后端（后端原样回传）。
 * M4 会用它作为 LangGraph 的 configurable.thread_id，
 * 实现多轮对话的记忆持久化。
 */

/** localStorage 里的存储键名 */
const KEY = "agent.thread_id";

/**
 * 获取当前会话 ID，不存在则创建一个。
 *
 * 服务端渲染（SSR）时没有 window，返回固定值避免报错。
 */
export function getThreadId(): string {
  if (typeof window === "undefined") return "ssr";
  let id = window.localStorage.getItem(KEY);
  if (!id) {
    id = crypto.randomUUID();
    window.localStorage.setItem(KEY, id);
  }
  return id;
}

/**
 * 重置会话 ID —— 对应"新建会话"按钮。
 *
 * M4 的"切换会话"下拉框也会用到这个函数。
 */
export function resetThreadId(): string {
  const id = crypto.randomUUID();
  if (typeof window !== "undefined") {
    window.localStorage.setItem(KEY, id);
  }
  return id;
}
