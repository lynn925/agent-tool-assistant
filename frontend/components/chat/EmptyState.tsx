"use client";

import { Calculator, Globe, Thermometer } from "lucide-react";

import { Button } from "@/components/ui/button";

/**
 * 空状态（M6）。
 *
 * 没有消息时显示的引导页 —— 告诉用户这个 Agent 能干什么，
 * 并给出三个可以直接点的示例 prompt。
 */

/** 示例 prompt。点击后直接填进输入框。 */
export const EXAMPLE_PROMPTS = [
  {
    icon: Thermometer,
    label: "查天气",
    prompt: "上海现在天气怎么样？",
  },
  {
    icon: Globe,
    label: "联网搜索",
    prompt: "帮我搜一下 LangGraph 的官方教程",
  },
  {
    icon: Calculator,
    label: "算一算",
    prompt: "帮我算一下 (123 + 456) * 789",
  },
] as const;

export function EmptyState({ onPick }: { onPick: (prompt: string) => void }) {
  return (
    <div className="flex flex-col items-center justify-center gap-6 py-12 text-center">
      <div className="flex flex-col gap-2">
        <h2 className="text-lg font-semibold">有什么可以帮你？</h2>
        <p className="text-sm text-muted-foreground">
          我能查天气、联网搜索、算数学表达式，也可以把多步任务拆开依次执行。
        </p>
      </div>

      {/* 三个示例 prompt */}
      <div className="grid w-full max-w-lg grid-cols-1 gap-2 sm:grid-cols-3">
        {EXAMPLE_PROMPTS.map(({ icon: Icon, label, prompt }) => (
          <Button
            key={prompt}
            variant="outline"
            className="h-auto flex-col items-start gap-1.5 py-3 text-left"
            onClick={() => onPick(prompt)}
          >
            <span className="flex items-center gap-1.5 text-xs text-muted-foreground">
              <Icon className="size-3.5" />
              {label}
            </span>
            <span className="line-clamp-2 text-sm font-normal leading-snug">
              {prompt}
            </span>
          </Button>
        ))}
      </div>
    </div>
  );
}
