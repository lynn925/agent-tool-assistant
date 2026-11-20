"use client";

import type { ChatMessage } from "@/lib/types";
import { PlanPanel } from "@/components/chat/PlanPanel";
import { ToolCallCard } from "@/components/chat/ToolCallCard";

/**
 * 一条消息气泡。
 *
 * 用户消息右对齐蓝底，助手消息左对齐灰底。
 * 助手消息下方按顺序渲染：
 *   1. 任务计划面板（M3 有计划时才有）
 *   2. 工具调用卡片
 */
export function MessageBubble({ message }: { message: ChatMessage }) {
  const isUser = message.role === "user";

  return (
    <li className="flex flex-col gap-2">
      {/* 消息正文 */}
      <div
        className={
          isUser
            ? "self-end rounded-lg bg-primary px-3 py-2 text-sm text-primary-foreground"
            : "self-start rounded-lg bg-muted px-3 py-2 text-sm"
        }
      >
        <span className="mr-1 text-xs opacity-60">{isUser ? "你" : "Agent"}</span>
        {message.text}
      </div>

      {/* 任务计划面板（M3） */}
      {message.plan && message.plan.length > 0 ? (
        <div className="self-start">
          <PlanPanel steps={message.plan} />
        </div>
      ) : null}

      {/* 工具调用卡片列表 */}
      {message.toolCalls.length > 0 ? (
        <ul className="flex flex-col gap-2 self-start">
          {message.toolCalls.map((call) => (
            <li key={call.id}>
              <ToolCallCard call={call} />
            </li>
          ))}
        </ul>
      ) : null}
    </li>
  );
}
