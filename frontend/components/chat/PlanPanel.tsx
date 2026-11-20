"use client";

import type { TaskStep } from "@/lib/types";

/** 状态 → 中文标签 */
const STATUS_LABELS: Record<TaskStep["status"], string> = {
  pending: "待执行",
  running: "执行中",
  done: "已完成",
  failed: "失败",
  skipped: "已跳过",
};

/** 状态 → 圆点样式 */
const DOT_STYLES: Record<TaskStep["status"], string> = {
  pending: "border-border bg-background",
  running: "border-amber-500 bg-amber-500 animate-pulse",
  done: "border-emerald-500 bg-emerald-500",
  failed: "border-red-500 bg-red-500",
  skipped: "border-amber-500 bg-amber-500/40",
};

/** 状态 → 文字颜色 */
const TEXT_STYLES: Record<TaskStep["status"], string> = {
  pending: "text-muted-foreground",
  running: "text-foreground",
  done: "text-foreground",
  failed: "text-red-600 dark:text-red-400",
  skipped: "text-amber-600 dark:text-amber-400",
};

/** 工具名 → 中文显示名 */
const TOOL_LABELS: Record<string, string> = {
  get_weather: "查询天气",
  web_search: "联网搜索",
  calculate: "计算器",
};

/**
 * 任务计划面板（M3）。
 *
 * 展示 planner 生成的步骤清单，以及每一步的实时状态。
 * 失败的步骤会标黄并说明原因。
 */
export function PlanPanel({ steps }: { steps: TaskStep[] }) {
  if (steps.length === 0) return null;

  return (
    <div className="rounded-lg border border-border bg-muted/30 p-3">
      <p className="mb-2 text-xs font-medium text-muted-foreground">执行计划</p>
      <ol className="flex flex-col gap-2">
        {steps.map((step) => {
          const toolLabel = step.tool ? TOOL_LABELS[step.tool] : null;
          return (
            <li key={step.id} className="flex items-start gap-2 text-sm">
              {/* 状态圆点 */}
              <span
                className={`mt-1.5 h-2 w-2 shrink-0 rounded-full border ${DOT_STYLES[step.status]}`}
              />
              <div className="min-w-0 flex-1">
                <p className={TEXT_STYLES[step.status]}>
                  {step.description}
                  {toolLabel ? (
                    <span className="ml-2 text-xs text-muted-foreground">
                      {toolLabel}
                    </span>
                  ) : null}
                </p>
                {/* 跳过/失败时说明原因 */}
                {step.status === "skipped" && step.error ? (
                  <p className="mt-0.5 text-xs text-amber-600 dark:text-amber-400">
                    执行失败（{step.error}），已跳过
                  </p>
                ) : null}
              </div>
              {/* 右侧状态标签 */}
              <span className="shrink-0 text-xs text-muted-foreground">
                {STATUS_LABELS[step.status]}
              </span>
            </li>
          );
        })}
      </ol>
    </div>
  );
}
