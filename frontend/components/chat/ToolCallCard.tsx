"use client";

import { useState } from "react";

import { TOOL_LABELS, type ToolCall } from "@/lib/types";

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

/** RAG 检索结果里的一条 chunk */
interface RagChunk {
  source?: string;
  page?: number;
  text?: string;
  similarity?: number;
  doc_id?: string;
}

/**
 * 判断一个工具结果是不是 RAG 检索结果。
 * RAG 返回 {results, count, sources}，别的工具不会长这样。
 */
function isRagResult(value: unknown): value is {
  results: RagChunk[];
  count: number;
  sources: string[];
} {
  return (
    typeof value === "object" &&
    value !== null &&
    Array.isArray((value as { results?: unknown }).results)
  );
}

/**
 * 单条检索片段。
 *
 * 正文可能上千字 —— 5 条片段能把整页撑到几千像素，
 * 用户要滚很久才看完。所以片段列表整体限高 + 一个滚动容器。
 *
 * 注意：只做**一层**滚动。外层列表滚 + 每条片段再滚会形成嵌套滚动区，
 * 触控板在这种结构下很难滚 —— 内容在内层，外层几乎不动。
 */
function RagChunkItem({ chunk }: { chunk: RagChunk }) {
  return (
    <div className="rounded border border-border bg-background p-2 text-xs">
      <div className="mb-1 flex flex-wrap items-center gap-2 text-muted-foreground">
        <span className="font-medium text-foreground">
          {chunk.source || "未知来源"}
        </span>
        {chunk.page ? <span>第 {chunk.page} 页</span> : null}
        {chunk.similarity !== undefined ? (
          <span>相似度 {chunk.similarity}</span>
        ) : null}
      </div>
      <p className="whitespace-pre-wrap break-words leading-relaxed">
        {chunk.text}
      </p>
    </div>
  );
}

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
  // 提取成局部变量才能让 TS 保持类型收窄（属性访问不会窄化）
  const ragResult =
    call.status === "ok" && isRagResult(call.result) ? call.result : null;

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
        {/* RAG：命中几条片段 */}
        {ragResult ? (
          <span className="rounded-full border border-border px-2 py-0.5 text-xs text-muted-foreground">
            {ragResult.count} 条片段
          </span>
        ) : null}
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

          {/* RAG：片段逐条展示，而不是甩一大坨 JSON */}
          {ragResult ? (
            <div className="space-y-2">
              <p className="text-xs text-muted-foreground">
                结果（{ragResult.count} 条片段）
              </p>
              {/* 整个片段列表限高并独立滚动 —— 不然会把页面撑得极长 */}
              <div className="scroll-thin max-h-80 space-y-2 overflow-y-auto rounded border border-border bg-muted/20 p-2 pr-3">
                {ragResult.results.map((chunk, i) => (
                  <RagChunkItem key={i} chunk={chunk} />
                ))}
              </div>
            </div>
          ) : (
            /* 执行结果：失败时显示错误码，成功时显示结果数据 */
            <div>
              <p className="mb-1 text-xs text-muted-foreground">
                {call.status === "failed" ? "错误" : "结果"}
              </p>
              <pre className="scroll-thin max-h-80 overflow-auto rounded bg-background p-2 text-xs">
                {JSON.stringify(
                  call.status === "failed" ? call.error : call.result,
                  null,
                  2,
                )}
              </pre>
            </div>
          )}
        </div>
      ) : null}
    </div>
  );
}
