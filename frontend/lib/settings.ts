/**
 * M6 设置项 —— 存在 localStorage，随请求发给后端。
 *
 * 设计要点：**设置不改变后端的全局配置**，只是"这次请求用这些值"。
 * 所以后端要把它们放进 LangGraph 的 configurable 里，
 * 每个请求独立生效 —— 改一次设置不会影响其他会话。
 */

/** 设置的存储键 */
const STORAGE_KEY = "agent.settings";

/**
 * ⚠️ 模型列表不在这里硬编码。
 *
 * 之前硬编码过一份（gpt-4o-mini / gpt-4o / MiniMax-M3），踩了坑：
 * 后端的 OPENAI_BASE_URL 指向 MiniMax，选 gpt-4o 必然报
 * "unknown model 'gpt-4o'"。硬编码的列表和后端配置很容易对不上。
 *
 * 现在模型列表由后端 /api/models 提供 —— 后端才知道 .env 里配了哪些 key、
 * 各个 provider 下面有哪些模型。见 components/chat/ModelSwitcher.tsx。
 */

export interface Settings {
  /** 模型名 */
  model: string;
  /** 聚合器的温度：0 = 稳定，1 = 发散 */
  temperature: number;
  /** 最大重试次数（不含首次尝试） */
  retryMaxAttempts: number;
}

/** 默认值 —— 与后端 .env 的默认值保持一致 */
export const DEFAULT_SETTINGS: Settings = {
  /**
   * 模型名。空字符串表示"用后端的默认模型" ——
   * 不在前端硬编码具体模型名，否则换 provider 时这里就过期了。
   * 真实默认值由后端 /api/models 的 default_model 提供。
   */
  model: "",
  temperature: 0.7,
  retryMaxAttempts: 3,
};

/** 重试次数的取值范围 */
export const RETRY_RANGE = { min: 0, max: 5 } as const;

function isBrowser(): boolean {
  return typeof window !== "undefined";
}

/**
 * 读取设置。
 *
 * 存坏了（JSON 解析失败）就回退到默认值 —— 不能因为一个坏数据
 * 就让整个应用白屏。
 */
export function getSettings(): Settings {
  if (!isBrowser()) return DEFAULT_SETTINGS;
  try {
    const raw = window.localStorage.getItem(STORAGE_KEY);
    if (!raw) return DEFAULT_SETTINGS;
    const parsed = JSON.parse(raw) as Partial<Settings>;
    return {
      model: parsed.model ?? DEFAULT_SETTINGS.model,
      temperature: parsed.temperature ?? DEFAULT_SETTINGS.temperature,
      retryMaxAttempts:
        parsed.retryMaxAttempts ?? DEFAULT_SETTINGS.retryMaxAttempts,
    };
  } catch {
    return DEFAULT_SETTINGS;
  }
}

/** 保存设置 */
export function saveSettings(settings: Settings): void {
  if (!isBrowser()) return;
  window.localStorage.setItem(STORAGE_KEY, JSON.stringify(settings));
}

/** 恢复默认设置 */
export function resetSettings(): void {
  if (!isBrowser()) return;
  window.localStorage.removeItem(STORAGE_KEY);
}
