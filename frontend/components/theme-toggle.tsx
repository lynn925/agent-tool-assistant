"use client";

import { Monitor, Moon, Sun } from "lucide-react";
import { useTheme } from "next-themes";
import { useEffect, useState } from "react";

import { Button } from "@/components/ui/button";

/**
 * 主题切换器（M6）。
 *
 * 三态循环：跟随系统 → 亮色 → 暗色 → 跟随系统。
 *
 * 为什么用单个按钮循环而不是下拉菜单：
 * 三个状态放在一个按钮里最省空间，且不用额外装 dropdown-menu。
 * 状态通过图标区分：系统=显示器，亮=太阳，暗=月亮。
 */
export function ThemeToggle() {
  const { theme, setTheme, resolvedTheme } = useTheme();
  // 挂载前不知道系统主题，渲染一个占位图标避免 SSR/CSR 不一致
  const [mounted, setMounted] = useState(false);

  useEffect(() => setMounted(true), []);

  if (!mounted) {
    return (
      <Button variant="ghost" size="icon" aria-label="切换主题">
        <Monitor />
      </Button>
    );
  }

  // theme 是用户的选择（light/dark/system），resolvedTheme 是实际生效的
  const isDark = resolvedTheme === "dark";
  const isSystem = theme === "system";

  function next() {
    if (theme === "system") setTheme("light");
    else if (theme === "light") setTheme("dark");
    else setTheme("system");
  }

  const label = isSystem
    ? "跟随系统"
    : isDark
      ? "暗色模式"
      : "亮色模式";

  return (
    <Button
      variant="ghost"
      size="icon"
      onClick={next}
      title={`${label}（点击切换）`}
      aria-label={`${label}（点击切换）`}
    >
      {isSystem ? <Monitor /> : isDark ? <Moon /> : <Sun />}
    </Button>
  );
}
