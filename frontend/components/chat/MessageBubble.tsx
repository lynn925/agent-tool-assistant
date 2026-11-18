"use client";

import type { ChatMessage } from "@/lib/types";
import { ToolCallCard } from "@/components/chat/ToolCallCard";

export function MessageBubble({ message }: { message: ChatMessage }) {
  const isUser = message.role === "user";

  return (
    <li className="flex flex-col gap-2">
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
