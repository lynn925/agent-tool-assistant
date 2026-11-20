"use client";

import { useRef, useState } from "react";

import { MessageBubble } from "@/components/chat/MessageBubble";
import { Button } from "@/components/ui/button";
import { Card, CardContent } from "@/components/ui/card";
import { Input } from "@/components/ui/input";
import { ScrollArea } from "@/components/ui/scroll-area";
import { chatStream } from "@/lib/api";
import { getThreadId } from "@/lib/thread";
import type { ChatMessage, ToolCall } from "@/lib/types";

/** 消息 ID 自增序号，保证同一页面内 ID 不重复 */
let messageSeq = 0;
function nextId(prefix: string): string {
  messageSeq += 1;
  return `${prefix}-${messageSeq}`;
}

export default function HomePage() {
  /** 聊天消息列表 */
  const [messages, setMessages] = useState<ChatMessage[]>([]);
  /** 输入框内容 */
  const [draft, setDraft] = useState("");
  /** 是否正在等待后端响应 */
  const [sending, setSending] = useState(false);
  /** 顶层错误提示（比如后端连不上） */
  const [error, setError] = useState<string | null>(null);
  /** 中止控制器，用于实现"停止"按钮 */
  const abortRef = useRef<AbortController | null>(null);

  /**
   * 更新指定助手消息。
   *
   * 所有流式事件最终都汇聚到这里：把 messages 数组里 id 匹配的那条替换掉。
   */
  function updateAssistant(
    assistantId: string,
    fn: (msg: ChatMessage) => ChatMessage,
  ) {
    setMessages((prev) =>
      prev.map((msg) => (msg.id === assistantId ? fn(msg) : msg)),
    );
  }

  /** 发送消息 */
  async function onSubmit(e: React.FormEvent) {
    e.preventDefault();
    const text = draft.trim();
    if (!text || sending) return;

    setError(null);
    // 先把用户消息和一条空的助手消息占位放进列表
    const userMsg: ChatMessage = {
      id: nextId("user"),
      role: "user",
      text,
      toolCalls: [],
    };
    const assistantId = nextId("assistant");
    const assistantMsg: ChatMessage = {
      id: assistantId,
      role: "assistant",
      text: "",
      toolCalls: [],
    };
    setMessages((prev) => [...prev, userMsg, assistantMsg]);
    setDraft("");
    setSending(true);

    const controller = new AbortController();
    abortRef.current = controller;

    try {
      // 建立 SSE 连接，把事件分发到状态更新
      await chatStream(text, getThreadId(), {
        signal: controller.signal,
        onEvent: (event) => {
          switch (event.event) {
            // 文本片段：追加到消息末尾
            case "content_delta": {
              const delta = event.data.delta;
              updateAssistant(assistantId, (msg) => ({
                ...msg,
                text: msg.text + delta,
              }));
              break;
            }

            // M3：完整计划，渲染计划面板
            case "plan_update": {
              const plan = event.data.plan;
              updateAssistant(assistantId, (msg) => ({
                ...msg,
                plan,
              }));
              break;
            }

            // M3：单步状态变化，更新计划面板里的对应步骤
            case "step_update": {
              const { id, status, description, tool } = event.data;
              updateAssistant(assistantId, (msg) => ({
                ...msg,
                plan: (msg.plan ?? []).map((step) =>
                  step.id === id
                    ? { ...step, status, description, tool: tool ?? undefined }
                    : step,
                ),
              }));
              break;
            }

            // M3：工具执行回执。
            // 注意 id 是步骤 ID（step-1 之类），不是 M2 的 tool_call id。
            case "tool_result": {
              const {
                id,
                name,
                args,
                ok,
                result,
                error: toolError,
                latency_ms,
              } = event.data;
              updateAssistant(assistantId, (msg) => ({
                ...msg,
                toolCalls: [
                  ...msg.toolCalls,
                  {
                    id,
                    name,
                    args: args ?? {},
                    status: ok ? "ok" : "failed",
                    result,
                    error: toolError ?? undefined,
                    latencyMs: latency_ms,
                  } satisfies ToolCall,
                ],
              }));
              break;
            }

            // 全局错误：挂到消息上
            case "error": {
              const { code, message } = event.data;
              updateAssistant(assistantId, (msg) => ({
                ...msg,
                error: { code, message },
              }));
              break;
            }

            default:
              break;
          }
        },
      });
    } catch (err) {
      if (controller.signal.aborted) {
        // 用户点了"停止"，删掉那条空的助手消息
        setMessages((prev) => prev.filter((m) => m.id !== assistantId));
      } else {
        const msg = err instanceof Error ? err.message : String(err);
        setError(`后端调用失败：${msg}`);
      }
    } finally {
      abortRef.current = null;
      setSending(false);
    }
  }

  /** 中断当前请求 */
  function onStop() {
    abortRef.current?.abort();
  }

  return (
    <main className="mx-auto flex min-h-screen w-full max-w-3xl flex-col gap-4 px-4 py-8">
      <header className="flex flex-col gap-1">
        <h1 className="text-2xl font-semibold">Agent Tool Assistant</h1>
        <p className="text-sm text-muted-foreground">
          M3 · LangGraph 多步任务编排：先规划步骤，再逐步执行，最后汇总。
        </p>
      </header>

      <Card className="flex-1">
        <CardContent className="p-0">
          <ScrollArea className="h-[60vh] px-4 py-4">
            {messages.length === 0 ? (
              <p className="text-sm text-muted-foreground">
                还没有消息。试试「上海现在天气怎么样」或「帮我算一下 2+2*3」。
              </p>
            ) : (
              <ul className="flex flex-col gap-3">
                {messages.map((m) => (
                  <MessageBubble key={m.id} message={m} />
                ))}
              </ul>
            )}
          </ScrollArea>
        </CardContent>
      </Card>

      {/* 顶层错误提示 */}
      {error ? (
        <p className="text-sm text-destructive">{error}</p>
      ) : null}

      {/* 输入区 */}
      <form onSubmit={onSubmit} className="flex gap-2">
        <Input
          value={draft}
          onChange={(e) => setDraft(e.target.value)}
          placeholder="说点什么…（回车发送）"
          disabled={sending}
          autoFocus
        />
        {/* 发送中就换成"停止"按钮 */}
        {sending ? (
          <Button type="button" variant="outline" onClick={onStop}>
            停止
          </Button>
        ) : (
          <Button type="submit" disabled={!draft.trim()}>
            发送
          </Button>
        )}
      </form>
    </main>
  );
}
