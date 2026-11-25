"use client";

/**
 * 流式生成指示器（M6）。
 *
 * 模型正在生成、但还没吐出第一个字时显示的三点动画。
 *
 * 为什么用 CSS 动画而不是 framer-motion：
 * 三个点的位移动画用纯 CSS 就够了，引入动画库不划算。
 */
export function StreamingDots() {
  return (
    <span
      className="inline-flex items-center gap-1"
      role="status"
      aria-label="正在生成"
    >
      {[0, 1, 2].map((i) => (
        <span
          key={i}
          className="h-1.5 w-1.5 animate-pulse rounded-full bg-muted-foreground"
          // 三个点错开 150ms，形成依次起伏的效果
          style={{ animationDelay: `${i * 150}ms` }}
        />
      ))}
    </span>
  );
}
