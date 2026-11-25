"use client";

import { Check, ChevronDown, MessageSquarePlus, Trash2 } from "lucide-react";

import { Button } from "@/components/ui/button";
import {
  DropdownMenu,
  DropdownMenuContent,
  DropdownMenuItem,
  DropdownMenuLabel,
  DropdownMenuSeparator,
  DropdownMenuTrigger,
} from "@/components/ui/dropdown-menu";
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
 * M6：从原生 select 换成 shadcn DropdownMenu。
 *
 * 为什么换：原生 select 在移动端体验差（iOS 上是全屏选择器），
 * 而且没法在选项里放图标和"当前选中"的勾选标记。
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

  const current = threads.find((t) => t.thread_id === currentId);

  return (
    <div className="flex items-center gap-2">
      {/* 会话下拉菜单 */}
      <DropdownMenu>
        <DropdownMenuTrigger asChild>
          <Button variant="outline" className="max-w-[240px] justify-between">
            <span className="truncate">
              {current ? displayName(current) : "当前会话"}
            </span>
            <ChevronDown className="opacity-50" />
          </Button>
        </DropdownMenuTrigger>

        <DropdownMenuContent align="start" className="w-[240px]">
          <DropdownMenuLabel>会话列表</DropdownMenuLabel>
          <DropdownMenuSeparator />
          {threads.length === 0 ? (
            <DropdownMenuItem disabled>还没有会话</DropdownMenuItem>
          ) : (
            threads.map((thread) => (
              <DropdownMenuItem
                key={thread.thread_id}
                onSelect={() => onSwitch(thread.thread_id)}
              >
                <Check
                  className={
                    thread.thread_id === currentId
                      ? "opacity-100"
                      : "opacity-0"
                  }
                />
                <span className="truncate">{displayName(thread)}</span>
              </DropdownMenuItem>
            ))
          )}
        </DropdownMenuContent>
      </DropdownMenu>

      {/* 新建会话 */}
      <Button onClick={onCreate} variant="outline" size="sm">
        <MessageSquarePlus />
        新会话
      </Button>

      {/* 清空当前会话的记忆 */}
      <Button onClick={onClear} variant="ghost" size="sm" disabled={busy}>
        <Trash2 />
        {busy ? "清空中…" : "清空"}
      </Button>
    </div>
  );
}
