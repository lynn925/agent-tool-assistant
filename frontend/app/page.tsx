"use client";

import { useEffect, useRef, useState } from "react";

import { MessageBubble } from "@/components/chat/MessageBubble";
import { ThreadSwitcher } from "@/components/chat/ThreadSwitcher";
import { Button } from "@/components/ui/button";
import { Card, CardContent } from "@/components/ui/card";
import { Input } from "@/components/ui/input";
import { ScrollArea } from "@/components/ui/scroll-area";
import { chatStream, clearMemory, getMemory } from "@/lib/api";
import {
  type LocalThread,
  createThread,
  getThreadId,
  listLocalThreads,
  setThreadId,
  touchThread,
} from "@/lib/thread";
import type { ChatMessage, ToolCall } from "@/lib/types";

/** 消息 ID 自增序号，保证同一页面内 ID 不重复 */
let messageSeq = 0;
function nextId(prefix: string): string {
  messageSeq += 1;
  return `${prefix}-${messageSeq}`;
}

/** M5：当前正在进行的重试（没有则为 null） */
interface RetryingState {
  /** 出错的层：tool 工具层 / llm 模型层 */
  layer: "tool" | "llm";
  /** 哪一步 */
  stage: string;
  /** 工具名（工具层才有） */
  name?: string;
  /** 即将进行的第几次重试 */
  attempt: number;
  /** 总共最多尝试几次 */
  maxAttempts: number;
  /** 失败原因 */
  message: string;
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
  /** 当前会话 ID */
  const [threadId, setThreadIdState] = useState("");
  /** 会话列表 */
  const [threads, setThreads] = useState<LocalThread[]>([]);
  /** 清空记忆进行中 */
  const [clearing, setClearing] = useState(false);
  /** M5：当前正在重试的提示 */
  const [retrying, setRetrying] = useState<RetryingState | null>(null);

  /**
   * 首次挂载：读出当前会话，加载它的历史消息。
   */
  useEffect(() => {
    const id = getThreadId();
    setThreadIdState(id);
    setThreads(listLocalThreads());
    void loadHistory(id);
  }, []);

  /**
   * 加载某个会话的历史消息。
   *
   * 后端存的是纯文本消息（user/assistant），
   * 工具调用和计划面板的历史不恢复 —— 那部分是过程数据。
   */
  async function loadHistory(id: string) {
    try {
      const { messages: history } = await getMemory(id);
      if (history.length === 0) {
        setMessages([]);
        return;
      }
      setMessages(
        history.map((m) => ({
          id: nextId(m.role),
          role: m.role,
          text: m.text,
          toolCalls: [],
        })),
      );
    } catch {
      // 后端不可达时静默失败，页面照常能用
      setMessages([]);
    }
  }

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
      await chatStream(text, threadId, {
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
            // M5：error 和 retry 也要透传 —— 否则失败原因和重试次数
            // 不会显示在计划面板里。
            case "step_update": {
              const { id, status, description, tool, error, retry } = event.data;
              updateAssistant(assistantId, (msg) => ({
                ...msg,
                plan: (msg.plan ?? []).map((step) =>
                  step.id === id
                    ? {
                        ...step,
                        status,
                        description,
                        tool: tool ?? undefined,
                        error: error ?? null,
                        retry: retry ?? step.retry,
                      }
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
                retry,
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
                    retry,
                    latencyMs: latency_ms,
                  } satisfies ToolCall,
                ],
              }));
              break;
            }

            // M5：正在重试。实时提示用户「系统在自动重试」，
            // 而不是让用户对着一个卡住的界面干等。
            case "retry": {
              const { layer, stage, name, attempt, max_attempts, message } =
                event.data;
              setRetrying({
                layer,
                stage,
                name,
                attempt,
                maxAttempts: max_attempts,
                message,
              });
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
      // 这次对话已经进了后端记忆，把它记到本地列表
      touchThread(threadId);
      setThreads(listLocalThreads());
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
      // 重试提示只在请求期间显示，结束后清掉
      setRetrying(null);
    }
  }

  /** 中断当前请求 */
  function onStop() {
    abortRef.current?.abort();
  }

  /** 切换会话 */
  function onSwitch(id: string) {
    setThreadId(id);
    setThreadIdState(id);
    void loadHistory(id);
  }

  /** 新建会话 */
  function onCreate() {
    const id = createThread();
    setThreadIdState(id);
    setMessages([]);
    setThreads(listLocalThreads());
  }

  /** 清空当前会话的记忆 */
  async function onClear() {
    setClearing(true);
    setError(null);
    try {
      await clearMemory(threadId);
      setMessages([]);
    } catch (err) {
      const msg = err instanceof Error ? err.message : String(err);
      setError(`清空失败：${msg}`);
    } finally {
      setClearing(false);
    }
  }

  return (
    <main className="mx-auto flex min-h-screen w-full max-w-3xl flex-col gap-4 px-4 py-8">
      <header className="flex flex-col gap-3">
        <div className="flex flex-col gap-1">
          <h1 className="text-2xl font-semibold">Agent Tool Assistant</h1>
          <p className="text-sm text-muted-foreground">
            M5 · 多步任务编排 + 会话记忆 + 错误自动重试。
          </p>
        </div>
        <ThreadSwitcher
          threads={threads}
          currentId={threadId}
          onSwitch={onSwitch}
          onCreate={onCreate}
          onClear={onClear}
          busy={clearing}
        />
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

      {/* M5：重试提示。放在消息区下方，输入框上方 —— 不打断阅读流 */}
      {retrying ? (
        <p className="flex items-center gap-2 text-xs text-amber-600 dark:text-amber-400">
          <span className="h-1.5 w-1.5 animate-pulse rounded-full bg-amber-500" />
          {retrying.layer === "tool"
            ? `${retrying.name ?? "工具"} 调用失败，正在重试（第 ${retrying.attempt}/${retrying.maxAttempts - 1} 次）`
            : `模型调用失败，正在重试（第 ${retrying.attempt}/${retrying.maxAttempts - 1} 次）`}
          ：{retrying.message}
        </p>
      ) : null}

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
