"use client";

import { useState } from "react";

import type { ToolCall } from "@/lib/types";

/** 工具名 → 中文显示名 */
const TOOL_LABELS: Record<string, string> = {
  get_weather: "查询天气",
  web_search: "联网搜索",
  calculate: "计算器",
};

/** 状态 → 徽章样式（边框色 + 文字色） */
const STATUS_STYLES: Record<ToolCall["status"], string> = {
  pending: "border-border text-muted-foreground",
  running: "border-border text-muted-foreground",
  ok: "border-emerald-500/40 text-emerald-600 dark:text-emerald-400",
  failed: "border-red-500/40 text-red-600 dark:text-red-400",
};

/** 状态 → 中文标签 */
const STATUS_LABELS: Record<ToolCall["status"], string> = {
  pending: "等待中",
  running: "执行中",
  ok: "成功",
  failed: "失败",
};

/**
 * 单个工具调用的折叠卡片。
 *
 * 收起时显示：工具名 + 状态徽章 + 重试徽章 + 耗时。
 * 展开后显示：调用参数 + 执行结果（失败时显示错误码）。
 */
export function ToolCallCard({ call }: { call: ToolCall }) {
  const [open, setOpen] = useState(false);
  // 未知工具就显示原始工具名
  const label = TOOL_LABELS[call.name] ?? call.name;

  return (
    <div className="rounded-lg border border-border bg-muted/40 text-sm">
      {/* 整个头部可点击，切换展开/收起 */}
      <button
        type="button"
        onClick={() => setOpen((v) => !v)}
        className="flex w-full items-center gap-2 px-3 py-2 text-left"
      >
        <span className="font-medium">{label}</span>
        <span
          className={`rounded-full border px-2 py-0.5 text-xs ${STATUS_STYLES[call.status]}`}
        >
          {STATUS_LABELS[call.status]}
        </span>
        {/* M5：重试过才显示徽章 */}
        {call.retry && call.retry > 0 ? (
          <span
            className="rounded-full border border-amber-500/40 px-2 py-0.5 text-xs text-amber-600 dark:text-amber-400"
            title="发生过瞬时错误，已自动重试"
          >
            🔁 重试 {call.retry} 次
          </span>
        ) : null}
        {/* 有耗时才显示 */}
        {call.latencyMs !== undefined ? (
          <span className="text-xs text-muted-foreground">
            {Math.round(call.latencyMs)}ms
          </span>
        ) : null}
        <span className="ml-auto text-xs text-muted-foreground">
          {open ? "收起" : "展开"}
        </span>
      </button>

      {open ? (
        <div className="space-y-2 border-t border-border px-3 py-2">
          {/* 调用参数 */}
          <div>
            <p className="mb-1 text-xs text-muted-foreground">参数</p>
            <pre className="overflow-x-auto rounded bg-background p-2 text-xs">
              {JSON.stringify(call.args, null, 2)}
            </pre>
          </div>
          {/* 执行结果：失败时显示错误码，成功时显示结果数据 */}
          <div>
            <p className="mb-1 text-xs text-muted-foreground">
              {call.status === "failed" ? "错误" : "结果"}
            </p>
            <pre className="overflow-x-auto rounded bg-background p-2 text-xs">
              {JSON.stringify(
                call.status === "failed" ? call.error : call.result,
                null,
                2,
              )}
            </pre>
          </div>
        </div>
      ) : null}
    </div>
  );
}
