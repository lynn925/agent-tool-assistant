"use client";

import { Calculator, FileSearch, Globe, Thermometer } from "lucide-react";

import { Button } from "@/components/ui/button";

/**
 * 空状态（M6）。
 *
 * 没有消息时显示的引导页 —— 告诉用户这个 Agent 能干什么，
 * 并给出四个可以直接点的示例 prompt。
 */

/** 示例 prompt。点击后直接填进输入框。 */
export const EXAMPLE_PROMPTS = [
  {
    icon: Thermometer,
    label: "查天气",
    prompt: "上海现在天气怎么样？",
  },
  {
    icon: Calculator,
    label: "算一算",
    prompt: "帮我算一下 (123 + 456) * 789",
  },
  {
    icon: Globe,
    label: "联网搜索",
    prompt: "帮我搜一下 LangGraph 的官方教程",
  },
  {
    // 这条要走 search_docs 而不是 web_search —— 提示词里明确区分了
    // 内部文档和互联网公开信息，示例里带上"内部文档"能让 planner 路由正确。
    icon: FileSearch,
    label: "检索文档",
    prompt: "内部文档里三方施工统计分析描述了哪些内容？",
  },
] as const;

export function EmptyState({ onPick }: { onPick: (prompt: string) => void }) {
  return (
    <div className="flex flex-col items-center justify-center gap-6 py-12 text-center">
      <div className="flex flex-col gap-2">
        <h2 className="text-lg font-semibold">有什么可以帮你？</h2>
        <p className="text-sm text-muted-foreground">
          我能查天气、联网搜索、计算数学表达式，也能检索内部文档并把复杂需求拆成多步完成。
        </p>
      </div>

      {/* 四个示例 prompt —— 两列 × 两行 */}
      <div className="grid w-full max-w-lg grid-cols-1 gap-2 sm:grid-cols-2">
        {EXAMPLE_PROMPTS.map(({ icon: Icon, label, prompt }) => (
          <Button
            key={prompt}
            variant="outline"
            className="h-auto w-full min-w-0 flex-col items-start gap-1.5 whitespace-normal py-3 text-left"
            onClick={() => onPick(prompt)}
          >
            <span className="flex items-center gap-1.5 text-xs text-muted-foreground">
              <Icon className="size-3.5" />
              {label}
            </span>
            {/* whitespace-normal 覆盖 Button 基类的 nowrap，
                min-w-0 + break-words 让长 prompt 在按钮内换行而不是溢出 */}
            <span className="line-clamp-2 w-full min-w-0 break-words text-sm font-normal leading-snug">
              {prompt}
            </span>
          </Button>
        ))}
      </div>
    </div>
  );
}
