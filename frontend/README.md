# Frontend — Next.js + shadcn/ui

## 启动

```bash
npm install
cp .env.example .env.local   # 默认值即可
npm run dev                  # http://localhost:3000
```

## 当前里程碑（M1）

- Next.js 16 App Router + TypeScript
- Tailwind v4 + shadcn/ui (button / input / card / scroll-area)
- 最小聊天页面：调 `http://localhost:8000/api/echo` 回显
- 通过 `lib/api.ts` 调用后端，默认 `NEXT_PUBLIC_BACKEND_URL=http://localhost:8000`

## 加 shadcn 组件（M6 阶段常用）

```bash
npx shadcn@latest add toast dialog badge avatar skeleton tabs dropdown-menu
```

## 目录

```
app/
  layout.tsx        # 全局布局
  page.tsx          # 主页（聊天 UI）
  globals.css       # Tailwind + 主题变量
components/
  ui/               # shadcn 原子组件
lib/
  api.ts            # 后端 fetch 封装
  utils.ts          # cn() 工具
```
