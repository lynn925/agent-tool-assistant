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

let messageSeq = 0;
function nextId(prefix: string): string {
  messageSeq += 1;
  return `${prefix}-${messageSeq}`;
}

export default function HomePage() {
  const [messages, setMessages] = useState<ChatMessage[]>([]);
  const [draft, setDraft] = useState("");
  const [sending, setSending] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const abortRef = useRef<AbortController | null>(null);

  function updateAssistant(
    assistantId: string,
    fn: (msg: ChatMessage) => ChatMessage,
  ) {
    setMessages((prev) =>
      prev.map((msg) => (msg.id === assistantId ? fn(msg) : msg)),
    );
  }

  async function onSubmit(e: React.FormEvent) {
    e.preventDefault();
    const text = draft.trim();
    if (!text || sending) return;

    setError(null);
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
      await chatStream(text, getThreadId(), {
        signal: controller.signal,
        onEvent: (event) => {
          switch (event.event) {
            case "content_delta": {
              const delta = event.data.delta;
              updateAssistant(assistantId, (msg) => ({
                ...msg,
                text: msg.text + delta,
              }));
              break;
            }
            case "tool_call": {
              const { id, name, args } = event.data;
              updateAssistant(assistantId, (msg) => ({
                ...msg,
                toolCalls: [
                  ...msg.toolCalls,
                  { id, name, args, status: "running" } satisfies ToolCall,
                ],
              }));
              break;
            }
            case "tool_result": {
              const { id, ok, result, error: toolError, latency_ms } = event.data;
              updateAssistant(assistantId, (msg) => ({
                ...msg,
                toolCalls: msg.toolCalls.map((call) =>
                  call.id === id
                    ? {
                        ...call,
                        status: ok ? "ok" : "failed",
                        result,
                        error: toolError,
                        latencyMs: latency_ms,
                      }
                    : call,
                ),
              }));
              break;
            }
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
        // user cancelled — drop the empty bubble
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

  function onStop() {
    abortRef.current?.abort();
  }

  return (
    <main className="mx-auto flex min-h-screen w-full max-w-3xl flex-col gap-4 px-4 py-8">
      <header className="flex flex-col gap-1">
        <h1 className="text-2xl font-semibold">Agent Tool Assistant</h1>
        <p className="text-sm text-muted-foreground">
          M2 · LangGraph 工具调用（天气 / 搜索 / 计算器）+ SSE 流式输出。
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

      {error ? (
        <p className="text-sm text-destructive">{error}</p>
      ) : null}

      <form onSubmit={onSubmit} className="flex gap-2">
        <Input
          value={draft}
          onChange={(e) => setDraft(e.target.value)}
          placeholder="说点什么…（回车发送）"
          disabled={sending}
          autoFocus
        />
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
