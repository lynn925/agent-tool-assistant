"use client";

import { Check, ChevronDown, Cpu } from "lucide-react";
import { useEffect, useState } from "react";

import {
  DropdownMenu,
  DropdownMenuContent,
  DropdownMenuItem,
  DropdownMenuLabel,
  DropdownMenuSeparator,
  DropdownMenuTrigger,
} from "@/components/ui/dropdown-menu";
import { listModels, type ProviderInfo } from "@/lib/api";

/**
 * 模型切换器（M6）。
 *
 * 放在输入框旁边，可以随时切换 —— 不用去设置页。
 *
 * 模型列表来自后端 /api/models：后端才知道 .env 里配了哪些 key。
 * 没配 key 的 provider 会置灰 —— 选了只会得到一个 401，不如不让选。
 */
export function ModelSwitcher({
  value,
  onChange,
}: {
  /** 当前选中的模型名 */
  value: string;
  /** 切换模型 */
  onChange: (model: string) => void;
}) {
  const [providers, setProviders] = useState<ProviderInfo[]>([]);
  const [loading, setLoading] = useState(true);

  // 拉一次模型列表
  useEffect(() => {
    let cancelled = false;
    listModels()
      .then((data) => {
        if (!cancelled) setProviders(data.providers);
      })
      .catch(() => {
        // 后端不可达时不显示任何模型，但不影响聊天
        if (!cancelled) setProviders([]);
      })
      .finally(() => {
        if (!cancelled) setLoading(false);
      });
    return () => {
      cancelled = true;
    };
  }, []);

  // 当前模型属于哪个 provider —— 用来在按钮上显示「MiniMax / DeepSeek」
  const currentProvider = providers.find((p) =>
    p.models.some((m) => m === value),
  );

  return (
    <DropdownMenu>
      <DropdownMenuTrigger asChild>
        <button
          type="button"
          className="inline-flex h-9 max-w-[220px] items-center gap-1.5 rounded-md border border-input bg-background px-3 text-sm transition-colors hover:bg-accent focus-visible:outline-none focus-visible:ring-1 focus-visible:ring-ring disabled:opacity-50"
          title={`当前模型：${value}`}
        >
          <Cpu className="size-3.5 shrink-0 opacity-70" />
          <span className="truncate">
            {loading ? "加载中…" : (currentProvider?.label ?? value)}
          </span>
          <ChevronDown className="size-3.5 shrink-0 opacity-50" />
        </button>
      </DropdownMenuTrigger>

      <DropdownMenuContent align="start" className="w-[260px]">
        {providers.length === 0 ? (
          <DropdownMenuItem disabled>没有可用的模型</DropdownMenuItem>
        ) : (
          providers.map((provider, idx) => (
            <div key={provider.id}>
              {idx > 0 ? <DropdownMenuSeparator /> : null}
              <DropdownMenuLabel className="flex items-center justify-between">
                <span>{provider.label}</span>
                {!provider.configured ? (
                  <span className="text-xs font-normal text-muted-foreground">
                    未配置 key
                  </span>
                ) : null}
              </DropdownMenuLabel>

              {provider.models.map((model) => (
                <DropdownMenuItem
                  key={model}
                  // 没配 key 的 provider 不让选 —— 选了只会报错
                  disabled={!provider.configured}
                  onSelect={() => onChange(model)}
                  className="pl-8"
                >
                  <Check
                    className={
                      model === value ? "opacity-100" : "opacity-0"
                    }
                  />
                  <span className="truncate">{model}</span>
                </DropdownMenuItem>
              ))}
            </div>
          ))
        )}
      </DropdownMenuContent>
    </DropdownMenu>
  );
}
