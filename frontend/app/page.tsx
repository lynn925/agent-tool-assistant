"use client";

import { Settings } from "lucide-react";
import { useRouter } from "next/navigation";
import { useEffect, useRef, useState } from "react";

import { MessageBubble } from "@/components/chat/MessageBubble";
import { EmptyState } from "@/components/chat/EmptyState";
import { ModelSwitcher } from "@/components/chat/ModelSwitcher";
import { ThreadSwitcher } from "@/components/chat/ThreadSwitcher";
import { ThemeToggle } from "@/components/theme-toggle";
import { Button } from "@/components/ui/button";
import { Card, CardContent } from "@/components/ui/card";
import { Input } from "@/components/ui/input";
import { ScrollArea } from "@/components/ui/scroll-area";
import { chatStream, clearMemory, getMemory } from "@/lib/api";
import { getSettings, saveSettings } from "@/lib/settings";
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
  const router = useRouter();
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
  /** M6：聊天区的 viewport 元素，用于自动滚动 */
  const viewportRef = useRef<HTMLDivElement | null>(null);
  /** M6：用户是否手动往上滚了 —— 手动滚动后就不该再自动往下拽 */
  const [pinnedToBottom, setPinnedToBottom] = useState(true);
  /** M6：当前选中的模型（输入框旁边的切换器控制） */
  const [model, setModel] = useState("");

  /**
   * M6：切换模型时同步到设置里 —— 这样刷新页面后选中的模型还在。
   */
  function onModelChange(next: string) {
    setModel(next);
    saveSettings({ ...getSettings(), model: next });
  }

  /**
   * M6：自动滚动到底部。
   *
   * 两个细节：
   *  1. 用 requestAnimationFrame 节流 —— 流式时每个 delta 都会触发一次，
   *     不节流会抖。
   *  2. 只在「用户本来就贴着底部」时才滚。手动往上翻历史时不该被拽回底部。
   */
  function scrollToBottom() {
    if (!pinnedToBottom) return;
    const el = viewportRef.current;
    if (!el) return;
    requestAnimationFrame(() => {
      el.scrollTop = el.scrollHeight;
    });
  }

  /**
   * M6：监听用户的滚动，判断他是否还贴着底部。
   *
   * 距离底部 32px 以内算「贴着」—— 留一点余量，
   * 否则滚动动画的最后一点点位移就会误判成「用户上翻了」。
   */
  function onViewportScroll() {
    const el = viewportRef.current;
    if (!el) return;
    const distance = el.scrollHeight - el.scrollTop - el.clientHeight;
    setPinnedToBottom(distance < 32);
  }

  /**
   * 首次挂载：读出当前会话，加载它的历史消息。
   */
  useEffect(() => {
    const id = getThreadId();
    setThreadIdState(id);
    setThreads(listLocalThreads());
    // M6：恢复上次选中的模型
    setModel(getSettings().model);
    void loadHistory(id);
  }, []);

  /**
   * M6：消息变化时自动滚到底部。
   *
   * 依赖整个 messages 数组 —— 流式时每来一个 delta 数组就变了，
   * 于是会持续滚动，呈现"打字机往下推"的效果。
   */
  useEffect(() => {
    scrollToBottom();
  }, [messages]);

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
    setDraft("");
    await sendMessage(text);
  }

  /**
   * M6：空状态里点了示例 prompt —— 填进输入框。
   *
   * 只填不自动发 —— 让用户先看一眼再决定要不要改。
   */
  function onPickExample(prompt: string) {
    setDraft(prompt);
  }

  /**
   * M6：重发某条用户消息。
   *
   * 用**同一个 thread_id**，这样后端的记忆是连贯的 ——
   * 重发不是在开新会话，而是在同一个会话里再问一次。
   */
  function onResend(text: string) {
    if (sending) return;
    void sendMessage(text);
  }

  /** 真正发一条消息（发送和重发共用） */
  async function sendMessage(text: string) {
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
    setSending(true);

    const controller = new AbortController();
    abortRef.current = controller;

    try {
      // 建立 SSE 连接，把事件分发到状态更新
      await chatStream(text, threadId, {
        signal: controller.signal,
        // M6：带上设置页里的设置（每次发送时读取，改完立刻生效）。
        // 模型用切换器当前选中的值 —— 它比设置里的更实时。
        settings: { ...getSettings(), model },
        onEvent: (event) => {
          switch (event.event) {
            // 文本片段：追加到消息末尾
            case "content_delta": {
              const delta = event.data.delta;
              updateAssistant(assistantId, (msg) => ({
                ...msg,
                // 模型经常在正文前带一两个换行（"\n\n(123 + 456)..."）。
                // 流式时不能 trim —— 那会把中间的分段也吃掉，
                // 只削掉**开头**的空白，正文内容一个字符不动。
                text: msg.text ? msg.text + delta : delta.replace(/^\s+/, ""),
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
    <main className="mx-auto flex h-dvh w-full max-w-3xl flex-col gap-4 overflow-hidden px-4 py-6">
      <header className="flex shrink-0 flex-col gap-3">
        <div className="flex items-start justify-between gap-2">
          <div className="flex flex-col gap-1">
            <h1 className="text-2xl font-semibold">Agent Tool Assistant</h1>
            <p className="text-sm text-muted-foreground">
              M6 · 多步任务编排 + 会话记忆 + 错误自动重试 + 暗色模式。
            </p>
          </div>
          {/* M6：主题切换 + 设置入口 */}
          <div className="flex shrink-0 items-center gap-1">
            <ThemeToggle />
            <Button
              variant="ghost"
              size="icon"
              onClick={() => router.push("/settings")}
              title="设置"
              aria-label="设置"
            >
              <Settings />
            </Button>
          </div>
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

      <Card className="flex flex-1 flex-col overflow-hidden">
        <CardContent className="min-h-0 flex-1 p-0">
          <ScrollArea
            className="h-full px-4 py-4"
            viewportRef={viewportRef}
            onScroll={onViewportScroll}
          >
            {messages.length === 0 ? (
              /* M6：空状态 —— 引导 + 三个示例 prompt */
              <EmptyState onPick={onPickExample} />
            ) : (
              <ul className="flex flex-col gap-3">
                {messages.map((m) => (
                  <MessageBubble
                    key={m.id}
                    message={m}
                    onResend={m.role === "user" ? onResend : undefined}
                  />
                ))}
              </ul>
            )}
          </ScrollArea>
        </CardContent>
      </Card>

      {/* M5：重试提示。放在消息区下方，输入框上方 —— 不打断阅读流 */}
      {retrying ? (
        <p className="flex shrink-0 items-center gap-2 text-xs text-amber-600 dark:text-amber-400">
          <span className="h-1.5 w-1.5 animate-pulse rounded-full bg-amber-500" />
          {retrying.layer === "tool"
            ? `${retrying.name ?? "工具"} 调用失败，正在重试（第 ${retrying.attempt}/${retrying.maxAttempts - 1} 次）`
            : `模型调用失败，正在重试（第 ${retrying.attempt}/${retrying.maxAttempts - 1} 次）`}
          ：{retrying.message}
        </p>
      ) : null}

      {/* 顶层错误提示 */}
      {error ? (
        <p className="shrink-0 text-sm text-destructive">{error}</p>
      ) : null}

      {/* 输入区 */}
      <form onSubmit={onSubmit} className="flex shrink-0 gap-2">
        {/* M6：模型切换器，放在输入框左边 —— 随时可切 */}
        <ModelSwitcher value={model} onChange={onModelChange} />

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
