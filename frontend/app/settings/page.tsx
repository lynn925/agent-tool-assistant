"use client";

import { ArrowLeft, RotateCcw, Save } from "lucide-react";
import Link from "next/link";
import { useEffect, useState } from "react";

import { Button } from "@/components/ui/button";
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import { Input } from "@/components/ui/input";
import { Separator } from "@/components/ui/separator";
import { listModels, type ProviderInfo } from "@/lib/api";
import {
  type Settings,
  DEFAULT_SETTINGS,
  RETRY_RANGE,
  getSettings,
  resetSettings,
  saveSettings,
} from "@/lib/settings";

/**
 * 设置页（M6）。
 *
 * 设置只存在浏览器 localStorage 里，随请求发给后端 ——
 * 不改后端的全局配置，所以改完立刻生效，不用重启后端。
 */
export default function SettingsPage() {
  const [settings, setSettings] = useState<Settings>(DEFAULT_SETTINGS);
  const [saved, setSaved] = useState(false);
  const [providers, setProviders] = useState<ProviderInfo[]>([]);

  // 挂载后从 localStorage 读（SSR 阶段读不到）
  useEffect(() => {
    setSettings(getSettings());
    listModels()
      .then((data) => setProviders(data.providers))
      .catch(() => setProviders([]));
  }, []);

  function update<K extends keyof Settings>(key: K, value: Settings[K]) {
    setSettings((prev) => ({ ...prev, [key]: value }));
    setSaved(false);
  }

  function onSave() {
    saveSettings(settings);
    setSaved(true);
  }

  function onReset() {
    resetSettings();
    setSettings(DEFAULT_SETTINGS);
    setSaved(false);
  }

  return (
    <main className="mx-auto flex min-h-screen w-full max-w-2xl flex-col gap-4 px-4 py-8">
      <header className="flex items-center justify-between gap-2">
        <div className="flex flex-col gap-1">
          <h1 className="text-2xl font-semibold">设置</h1>
          <p className="text-sm text-muted-foreground">
            这些设置只保存在你的浏览器里，随每次请求发送给后端。
          </p>
        </div>
        <Button asChild variant="ghost" size="sm">
          <Link href="/">
            <ArrowLeft />
            返回
          </Link>
        </Button>
      </header>

      <Card>
        <CardHeader>
          <CardTitle className="text-base">模型</CardTitle>
        </CardHeader>
        <CardContent className="flex flex-col gap-4">
          <div className="flex flex-col gap-1.5">
            <label htmlFor="model" className="text-sm font-medium">
              模型名
            </label>
            <Input
              id="model"
              value={settings.model}
              onChange={(e) => update("model", e.target.value)}
              placeholder="留空则用后端默认模型"
            />
            <p className="text-xs text-muted-foreground">
              留空表示用后端 .env 里的默认模型。也可以从下面选，或自己填。
            </p>
          </div>

          {/* 各 provider 的模型（来自后端 /api/models） */}
          {providers.map((provider) => (
            <div key={provider.id} className="flex flex-col gap-2">
              <Separator />
              <div className="flex items-center justify-between">
                <span className="text-sm font-medium">{provider.label}</span>
                {!provider.configured ? (
                  <span className="text-xs text-muted-foreground">
                    未配置 key，请在 backend/.env 里设置
                    {provider.id.toUpperCase()}_API_KEY
                  </span>
                ) : null}
              </div>
              <div className="flex flex-wrap gap-2">
                {provider.models.map((model) => (
                  <Button
                    key={model}
                    variant={settings.model === model ? "default" : "outline"}
                    size="sm"
                    disabled={!provider.configured}
                    onClick={() => update("model", model)}
                  >
                    {model}
                  </Button>
                ))}
              </div>
            </div>
          ))}
        </CardContent>
      </Card>

      <Card>
        <CardHeader>
          <CardTitle className="text-base">生成参数</CardTitle>
        </CardHeader>
        <CardContent className="flex flex-col gap-4">
          <div className="flex flex-col gap-1.5">
            <div className="flex items-center justify-between">
              <label htmlFor="temperature" className="text-sm font-medium">
                温度
              </label>
              <span className="text-sm tabular-nums text-muted-foreground">
                {settings.temperature.toFixed(1)}
              </span>
            </div>
            <input
              id="temperature"
              type="range"
              min={0}
              max={1}
              step={0.1}
              value={settings.temperature}
              onChange={(e) =>
                update("temperature", Number(e.target.value))
              }
              className="h-2 w-full cursor-pointer appearance-none rounded-full bg-muted accent-primary"
            />
            <p className="text-xs text-muted-foreground">
              越低越稳定（适合查天气、算数），越高越发散（适合写作）。
              任务规划器固定用 0.2，不受这里影响。
            </p>
          </div>

          <Separator />

          <div className="flex flex-col gap-1.5">
            <div className="flex items-center justify-between">
              <label htmlFor="retry" className="text-sm font-medium">
                最大重试次数
              </label>
              <span className="text-sm tabular-nums text-muted-foreground">
                {settings.retryMaxAttempts}
              </span>
            </div>
            <input
              id="retry"
              type="range"
              min={RETRY_RANGE.min}
              max={RETRY_RANGE.max}
              step={1}
              value={settings.retryMaxAttempts}
              onChange={(e) =>
                update("retryMaxAttempts", Number(e.target.value))
              }
              className="h-2 w-full cursor-pointer appearance-none rounded-full bg-muted accent-primary"
            />
            <p className="text-xs text-muted-foreground">
              工具或模型调用遇到临时故障时自动重试，退避 1s / 2s / 4s。
              设成 0 表示不重试。
            </p>
          </div>
        </CardContent>
      </Card>

      <div className="flex items-center justify-end gap-2">
        <Button variant="ghost" onClick={onReset}>
          <RotateCcw />
          恢复默认
        </Button>
        <Button onClick={onSave}>
          <Save />
          {saved ? "已保存" : "保存"}
        </Button>
      </div>

      {saved ? (
        <p className="text-sm text-muted-foreground">
          已保存。设置会在下一次发送消息时生效。
        </p>
      ) : null}
    </main>
  );
}
