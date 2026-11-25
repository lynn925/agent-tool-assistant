"use client";

import { ThemeProvider as NextThemesProvider } from "next-themes";
import type { ComponentProps } from "react";

/**
 * 主题 Provider（M6）。
 *
 * 挂到 <html> 上，负责给 <html> 加/删 `.dark` 类。
 *
 * 为什么要用 next-themes 而不是自己写：
 *  - 服务端渲染时读不到 localStorage，会导致闪烁（先亮后暗）
 *  - next-themes 内置了 suppressHydrationWarning 的处理
 *
 * attribute="class" 是关键 —— 对应 globals.css 里的
 * `@custom-variant dark (&:is(.dark *))`。
 */
export function ThemeProvider({
  children,
  ...props
}: ComponentProps<typeof NextThemesProvider>) {
  return <NextThemesProvider {...props}>{children}</NextThemesProvider>;
}
