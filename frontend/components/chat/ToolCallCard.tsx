"use client";

import { useState } from "react";

import type { ToolCall } from "@/lib/types";

const TOOL_LABELS: Record<string, string> = {
  get_weather: "查询天气",
  web_search: "联网搜索",
  calculate: "计算器",
};

const STATUS_STYLES: Record<ToolCall["status"], string> = {
  pending: "border-border text-muted-foreground",
  running: "border-border text-muted-foreground",
  ok: "border-emerald-500/40 text-emerald-600 dark:text-emerald-400",
  failed: "border-red-500/40 text-red-600 dark:text-red-400",
};

const STATUS_LABELS: Record<ToolCall["status"], string> = {
  pending: "等待中",
  running: "执行中",
  ok: "成功",
  failed: "失败",
};

export function ToolCallCard({ call }: { call: ToolCall }) {
  const [open, setOpen] = useState(false);
  const label = TOOL_LABELS[call.name] ?? call.name;

  return (
    <div className="rounded-lg border border-border bg-muted/40 text-sm">
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
          <div>
            <p className="mb-1 text-xs text-muted-foreground">参数</p>
            <pre className="overflow-x-auto rounded bg-background p-2 text-xs">
              {JSON.stringify(call.args, null, 2)}
            </pre>
          </div>
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
