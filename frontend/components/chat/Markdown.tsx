"use client";

import { memo } from "react";
import ReactMarkdown, { type Components } from "react-markdown";
import rehypeKatex from "rehype-katex";
import remarkGfm from "remark-gfm";
import remarkMath from "remark-math";

import { cn } from "@/lib/utils";

/**
 * 助手消息的 Markdown 渲染。
 *
 * 为什么需要它 —— 评测发现的实际问题：
 *   模型输出 "**456831**"      → 之前直接显示星号
 *   模型输出 "\\(\\sqrt{2}\\)"  → 之前直接显示 LaTeX 源码
 *
 * 原因是消息正文以前是纯文本渲染（{text}），模型写什么就显示什么。
 * 加了渲染之后：加粗变粗体、列表成列表、LaTeX 成公式。
 *
 * 三个 remark/rehype 插件各管一件事：
 *   remark-gfm    GitHub 扩展语法（表格、删除线、自动链接）
 *   remark-math   把 $...$ / $$...$$ 识别成数学公式
 *   rehype-katex  把数学公式渲染成真正的排版（不是源码）
 */

/** 自定义渲染：让内容继承气泡的文字样式，别用 markdown 默认的 h1/p 间距 */
const components: Components = {
  p: ({ children }) => <p className="leading-relaxed">{children}</p>,
  ul: ({ children }) => (
    <ul className="my-1 list-disc space-y-0.5 pl-5">{children}</ul>
  ),
  ol: ({ children }) => (
    <ol className="my-1 list-decimal space-y-0.5 pl-5">{children}</ol>
  ),
  li: ({ children }) => <li className="leading-relaxed">{children}</li>,
  a: ({ children, href }) => (
    <a
      href={href}
      target="_blank"
      rel="noreferrer noopener"
      className="text-primary underline underline-offset-2"
    >
      {children}
    </a>
  ),
  code: ({ children, className }) => {
    // 行内代码没有 className，代码块才有
    const isBlock = Boolean(className?.startsWith("language-"));
    if (isBlock) {
      return (
        <code className="block overflow-x-auto rounded bg-background p-2 text-xs">
          {children}
        </code>
      );
    }
    return (
      <code className="rounded bg-background px-1 py-0.5 text-[0.9em]">
        {children}
      </code>
    );
  },
  pre: ({ children }) => (
    <pre className="scroll-thin my-2 max-h-80 overflow-auto rounded bg-background p-2 text-xs">
      {children}
    </pre>
  ),
  table: ({ children }) => (
    <div className="scroll-thin my-2 overflow-x-auto">
      <table className="w-full border-collapse text-xs">{children}</table>
    </div>
  ),
  th: ({ children }) => (
    <th className="border border-border bg-muted px-2 py-1 text-left font-medium">
      {children}
    </th>
  ),
  td: ({ children }) => (
    <td className="border border-border px-2 py-1 align-top">{children}</td>
  ),
  blockquote: ({ children }) => (
    <blockquote className="my-2 border-l-2 border-border pl-3 text-muted-foreground">
      {children}
    </blockquote>
  ),
  hr: () => <hr className="my-3 border-border" />,
};

export const Markdown = memo(function Markdown({
  content,
  className,
}: {
  content: string;
  className?: string;
}) {
  return (
    <div className={cn("text-sm", className)}>
      <ReactMarkdown
        remarkPlugins={[remarkGfm, remarkMath]}
        rehypePlugins={[rehypeKatex]}
        components={components}
      >
        {content}
      </ReactMarkdown>
    </div>
  );
});
