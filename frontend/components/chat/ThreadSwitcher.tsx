"use client";

import { Button } from "@/components/ui/button";
import type { LocalThread } from "@/lib/thread";

interface ThreadSwitcherProps {
  /** 所有会话 */
  threads: LocalThread[];
  /** 当前会话 ID */
  currentId: string;
  /** 切换会话 */
  onSwitch: (threadId: string) => void;
  /** 新建会话 */
  onCreate: () => void;
  /** 清空当前会话 */
  onClear: () => void;
  /** 是否正在处理（清空是异步的） */
  busy?: boolean;
}

/**
 * 会话切换器（M4）。
 *
 * 用原生 select 而非 shadcn 的 dropdown-menu —— 少装一个依赖，
 * 而且 select 在移动端体验更稳。
 */
export function ThreadSwitcher({
  threads,
  currentId,
  onSwitch,
  onCreate,
  onClear,
  busy = false,
}: ThreadSwitcherProps) {
  /** 显示名称：用户命名过就用名字，否则用短 ID */
  function displayName(thread: LocalThread): string {
    if (thread.name) return thread.name;
    return `会话 ${thread.thread_id.slice(0, 8)}`;
  }

  return (
    <div className="flex items-center gap-2">
      {/* 会话下拉框 */}
      <select
        value={currentId}
        onChange={(e) => onSwitch(e.target.value)}
        className="h-9 max-w-[220px] rounded-md border border-input bg-background px-3 text-sm focus-visible:outline-none focus-visible:ring-1 focus-visible:ring-ring"
      >
        {threads.map((thread) => (
          <option key={thread.thread_id} value={thread.thread_id}>
            {displayName(thread)}
          </option>
        ))}
        {threads.length === 0 ? (
          <option value={currentId}>当前会话</option>
        ) : null}
      </select>

      {/* 新建会话 */}
      <Button onClick={onCreate} variant="outline" size="sm">
        新会话
      </Button>

      {/* 清空当前会话的记忆 */}
      <Button onClick={onClear} variant="ghost" size="sm" disabled={busy}>
        {busy ? "清空中…" : "清空"}
      </Button>
    </div>
  );
}
