"use client";

import { TOOL_LABELS, type TaskStep } from "@/lib/types";

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

/**
 * 任务计划面板（M3）。
 *
 * 展示 planner 生成的步骤清单，以及每一步的实时状态。
 *
 * M5 的状态语义：
 *   done     成功（绿）
 *   failed   这步执行了但没成功（红）—— 已重试过或重试耗尽
 *   skipped  这步没法执行（黄）—— 工具不存在 / 参数非法
 *
 * failed 和 skipped 都是「这一步没拿到结果」，但不阻塞后续步骤。
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
                    /* 徽章而不是纯文字 —— 否则「文档检索」会跟描述混成一句，
                       读起来像是描述的一部分 */
                    <span className="ml-2 inline-block rounded-full border border-border px-1.5 py-px align-middle text-xs text-muted-foreground">
                      {toolLabel}
                    </span>
                  ) : null}
                </p>
                {/* 失败：说明原因，并标注重试次数 */}
                {step.status === "failed" && step.error ? (
                  <p className="mt-0.5 text-xs text-red-600 dark:text-red-400">
                    执行失败（{step.error}）
                    {step.retry && step.retry > 0
                      ? `，已重试 ${step.retry} 次`
                      : ""}
                  </p>
                ) : null}
                {/* 跳过：这步没法执行 */}
                {step.status === "skipped" && step.error ? (
                  <p className="mt-0.5 text-xs text-amber-600 dark:text-amber-400">
                    无法执行（{step.error}），已跳过
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
