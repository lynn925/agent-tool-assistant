"""Backend configuration loaded from environment / .env."""

from functools import lru_cache

from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    """Application settings sourced from env vars and backend/.env."""

    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        extra="ignore",
    )

    # OpenAI (M2+ required)
    openai_api_key: str = ""
    openai_model: str = "gpt-4o-mini"
    openai_base_url: str | None = None

    # DeepSeek —— 可选的第二个 provider。
    # 留空就不启用，用户在前端选 DeepSeek 模型时会得到清晰提示。
    deepseek_api_key: str = "sk-238a6b6600144b59ba0272634d830273"
    deepseek_base_url: str = "https://api.deepseek.com"
    #: DeepSeek 默认模型（前端切到 deepseek 时用它，除非用户指定了具体模型）
    deepseek_model: str = "deepseek-v4-pro"

    # SerpAPI (M2 search tool, optional in M1)
    serpapi_api_key: str = ""

    # CORS
    frontend_origin: str = "http://localhost:3000"

    # M4 记忆持久化：SQLite 数据库文件路径
    checkpoint_db_path: str = "data/checkpoints.db"

    # M5 错误恢复：最大重试次数（不含首次尝试）。
    # 3 次重试 = 最多 4 次调用，退避 1s/2s/4s。
    retry_max_attempts: int = 3


@lru_cache
def get_settings() -> Settings:
    return Settings()
