import type { Metadata } from "next";
import "./globals.css";

export const metadata: Metadata = {
  title: "Agent Tool Assistant",
  description: "AI Agent 工具调用助手 (LangGraph + OpenAI Function Calling)",
};

export default function RootLayout({
  children,
}: Readonly<{ children: React.ReactNode }>) {
  return (
    <html lang="zh-CN" suppressHydrationWarning>
      <body className="antialiased min-h-screen bg-background text-foreground">
        {children}
      </body>
    </html>
  );
}
