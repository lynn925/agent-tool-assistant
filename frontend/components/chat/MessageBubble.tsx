"use client";

import { Bot, RotateCcw, User } from "lucide-react";
import { useState } from "react";

import type { ChatMessage } from "@/lib/types";
import { PlanPanel } from "@/components/chat/PlanPanel";
import { StreamingDots } from "@/components/chat/StreamingDots";
import { ToolCallCard } from "@/components/chat/ToolCallCard";
import { Avatar, AvatarFallback } from "@/components/ui/avatar";
import { Button } from "@/components/ui/button";

/** 超过这个字数就折叠。 */
const FOLD_THRESHOLD = 300;

/**
 * 一条消息气泡。
 *
 * 用户消息右对齐蓝底，助手消息左对齐灰底。
 * 助手消息下方按顺序渲染：
 *   1. 任务计划面板（M3 有计划时才有）
 *   2. 工具调用卡片
 *
 * M6 的变化：
 *   - 用 avatar 组件替换原来的「你 / Agent」文字标签
 *   - 超过 300 字的长消息自动折叠，可展开
 *   - 助手消息支持「重发」
 */
export function MessageBubble({
  message,
  onResend,
}: {
  message: ChatMessage;
  /** 重发这条消息（可选 —— 用户消息才需要） */
  onResend?: (text: string) => void;
}) {
  const isUser = message.role === "user";
  // 长消息折叠状态
  const [expanded, setExpanded] = useState(false);

  const text = message.text;
  const isLong = text.length > FOLD_THRESHOLD;
  const shouldFold = isLong && !expanded;

  // 助手消息正在流式输出：还没拿到第一个字时显示三点动画
  const isStreaming = !isUser && text.length === 0;

  return (
    <li className="flex flex-col gap-2">
      {/* 消息主体：头像 + 气泡
          用户消息：气泡在左、头像在右
          助手消息：头像在左、气泡在右 */}
      <div className={isUser ? "flex items-start justify-end gap-2" : "flex items-start gap-2"}>
        {isUser ? null : <AgentAvatar />}

        <div className="flex min-w-0 max-w-[85%] flex-col gap-1">
          <div
            className={
              isUser
                ? "self-end rounded-lg bg-primary px-3 py-2 text-sm text-primary-foreground"
                : "self-start rounded-lg bg-muted px-3 py-2 text-sm"
            }
          >
            {isStreaming ? (
              <StreamingDots />
            ) : (
              <>
                {/* 折叠时只显示开头 */}
                {shouldFold ? `${text.slice(0, FOLD_THRESHOLD)}…` : text}
              </>
            )}
          </div>

          {/* 长消息的展开/收起按钮 */}
          {isLong ? (
            <button
              type="button"
              onClick={() => setExpanded((v) => !v)}
              className="self-start text-xs text-muted-foreground underline-offset-4 hover:underline"
            >
              {expanded ? "收起" : "展开全文"}
            </button>
          ) : null}

          {/* 错误提示：M6 之前后端发了 error 事件但前端没渲染，
              用户只能看到一条空消息。现在明确显示出来。 */}
          {message.error ? (
            <p className="self-start rounded-md border border-destructive/40 bg-destructive/10 px-2 py-1.5 text-xs text-destructive">
              {message.error.message}
            </p>
          ) : null}

          {/* 重发按钮：只给用户消息 */}
          {isUser && onResend ? (
            <Button
              variant="ghost"
              size="sm"
              className="self-end h-6 gap-1 px-2 text-xs text-muted-foreground"
              onClick={() => onResend(message.text)}
              title="重发这条消息"
            >
              <RotateCcw className="size-3" />
              重发
            </Button>
          ) : null}
        </div>

        {/* 用户消息头像在气泡右边 */}
        {isUser ? <UserAvatar /> : null}
      </div>

      {/* 任务计划面板（M3） */}
      {message.plan && message.plan.length > 0 ? (
        <div className="self-start pl-10">
          <PlanPanel steps={message.plan} />
        </div>
      ) : null}

      {/* 工具调用卡片列表 */}
      {message.toolCalls.length > 0 ? (
        <ul className="flex flex-col gap-2 self-start pl-10">
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

/** 助手头像 */
function AgentAvatar() {
  return (
    <Avatar className="size-7 shrink-0">
      <AvatarFallback className="bg-primary text-primary-foreground">
        <Bot className="size-4" />
      </AvatarFallback>
    </Avatar>
  );
}

/** 用户头像（放在气泡右边） */
function UserAvatar() {
  return (
    <Avatar className="size-7 shrink-0">
      <AvatarFallback className="bg-muted text-muted-foreground">
        <User className="size-4" />
      </AvatarFallback>
    </Avatar>
  );
}
