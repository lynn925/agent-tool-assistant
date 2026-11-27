/**
 * 基于 localStorage 的会话（thread）管理 —— M4。
 *
 * 职责：
 *   1. 记住当前会话 ID
 *   2. 记住用户自定义的会话名称
 *   3. 记住会话列表（后端持久化了真正的消息，前端只存元信息）
 *
 * 后端用 thread_id 读写 SQLite 里的记忆，
 * 前端只需要保证 thread_id 一致就行。
 */

/** 当前会话 ID 的存储键 */
const CURRENT_KEY = "agent.thread_id";

/** 会话名称表的存储键：thread_id -> 名称 */
const NAMES_KEY = "agent.thread_names";

/** 会话列表的存储键：保存已知的 thread_id 及时间戳 */
const LIST_KEY = "agent.thread_list";

export interface LocalThread {
  thread_id: string;
  /** 用户自定义的名称，没有则显示短 ID */
  name: string;
  /** 最后活跃时间戳（毫秒） */
  updated_at: number;
}

function isBrowser(): boolean {
  return typeof window !== "undefined";
}

/**
 * 获取当前会话 ID，不存在则创建一个。
 *
 * 服务端渲染（SSR）时没有 window，返回固定值避免报错。
 */
export function getThreadId(): string {
  if (!isBrowser()) return "ssr";
  let id = window.localStorage.getItem(CURRENT_KEY);
  if (!id) {
    id = crypto.randomUUID();
    window.localStorage.setItem(CURRENT_KEY, id);
  }
  return id;
}

/** 切换到指定会话 */
export function setThreadId(threadId: string): void {
  if (!isBrowser()) return;
  window.localStorage.setItem(CURRENT_KEY, threadId);
}

/**
 * 新建一个会话并切换过去。
 *
 * 注意：这只改前端状态，真正的记忆要等用户发了第一条消息才会写进后端。
 */
export function createThread(name?: string): string {
  const id = crypto.randomUUID();
  if (isBrowser()) {
    window.localStorage.setItem(CURRENT_KEY, id);
    if (name) {
      setThreadName(id, name);
    }
  }
  return id;
}

/** 读取会话名称表 */
function readNames(): Record<string, string> {
  if (!isBrowser()) return {};
  try {
    return JSON.parse(window.localStorage.getItem(NAMES_KEY) ?? "{}");
  } catch {
    return {};
  }
}

/** 设置会话的自定义名称 */
export function setThreadName(threadId: string, name: string): void {
  if (!isBrowser()) return;
  const names = readNames();
  names[threadId] = name;
  window.localStorage.setItem(NAMES_KEY, JSON.stringify(names));
}

/** 读取会话列表（含名称），按最后活跃时间倒序 */
export function listLocalThreads(): LocalThread[] {
  if (!isBrowser()) return [];
  const names = readNames();
  try {
    const list = JSON.parse(window.localStorage.getItem(LIST_KEY) ?? "[]");
    return list
      .map((t: LocalThread) => ({
        ...t,
        name: names[t.thread_id] ?? t.name ?? "",
      }))
      .sort((a: LocalThread, b: LocalThread) => b.updated_at - a.updated_at);
  } catch {
    return [];
  }
}

/** 把会话写进本地列表（存在则更新活跃时间） */
export function touchThread(threadId: string, name?: string): void {
  if (!isBrowser()) return;
  const list = listLocalThreads().filter((t) => t.thread_id !== threadId);
  list.push({
    thread_id: threadId,
    name: name ?? readNames()[threadId] ?? "",
    updated_at: Date.now(),
  });
  window.localStorage.setItem(LIST_KEY, JSON.stringify(list));
}

/**
 * 从本地列表移除会话。
 *
 * 注意：**只删前端元信息，不删后端记忆** ——
 * 后端的删除走 DELETE /api/threads/{id}，那是另一个操作。
 */
export function removeThread(threadId: string): void {
  if (!isBrowser()) return;
  const list = listLocalThreads().filter((t) => t.thread_id !== threadId);
  window.localStorage.setItem(LIST_KEY, JSON.stringify(list));
}

/**
 * 删除会话的**全部**本地痕迹 —— 列表项 + 用户命名。
 *
 * 之前 removeThread 只清列表，名称表里会留下孤儿 key。
 */
export function forgetThread(threadId: string): void {
  if (!isBrowser()) return;
  removeThread(threadId);

  const names = readNames();
  if (threadId in names) {
    delete names[threadId];
    window.localStorage.setItem(NAMES_KEY, JSON.stringify(names));
  }
}
