"""应用配置：全部来自环境变量（.env），密钥绝不硬编码。

使用 pydantic-settings，让配置在启动时强校验、在测试里可注入。
"""

from __future__ import annotations

from functools import lru_cache
from pathlib import Path

from pydantic import Field, field_validator
from pydantic_settings import BaseSettings, SettingsConfigDict

REPO_ROOT = Path(__file__).resolve().parent.parent


class Settings(BaseSettings):
    """全局配置。字段名校验大小写不敏感，对应 `.env.example`。"""

    model_config = SettingsConfigDict(
        env_file=str(REPO_ROOT / ".env"),
        env_file_encoding="utf-8",
        extra="ignore",
        case_sensitive=False,
    )

    # ---------- 应用 ----------
    app_env: str = "dev"
    app_host: str = "127.0.0.1"
    app_port: int = 8000
    app_timezone: str = "Asia/Shanghai"

    database_url: str = "sqlite:///./data/ai_daily.db"
    workspace_dir: str = "./workspace"

    # ---------- LLM ----------
    llm_provider: str = "deepseek"
    llm_base_url: str = "https://api.deepseek.com"
    llm_api_key: str = ""
    llm_model: str = "deepseek-chat"
    llm_temperature: float = 0.3
    llm_timeout_seconds: int = 90
    llm_mode: str = "real"  # real | mock
    llm_max_tokens: int = 4096
    agent_max_steps: int = 24
    agent_token_budget: int = 500_000

    # ---------- 新闻源 ----------
    news_bing_enabled: bool = True
    news_bing_endpoint: str = "https://www.bing.com/news/search"
    news_language: str = "zh-CN"
    news_rss_feeds: str = ""
    news_max_articles: int = 30

    # ---------- 推送 ----------
    push_channels: str = "web"
    feishu_webhook_url: str = ""
    feishu_secret: str = ""
    feishu_verify_ssl: bool = True
    smtp_host: str = ""
    smtp_port: int = 465
    smtp_user: str = ""
    smtp_password: str = Field(default="", repr=False)
    smtp_from: str = ""
    smtp_use_ssl: bool = True

    # ---------- 定时 ----------
    scheduler_enabled: bool = True
    daily_run_time: str = "08:00"

    # ---------- 派生值 ----------
    @field_validator("llm_mode")
    @classmethod
    def _check_llm_mode(cls, v: str) -> str:
        v = v.strip().lower()
        if v not in {"real", "mock"}:
            raise ValueError("LLM_MODE 必须是 real 或 mock")
        return v

    @field_validator("daily_run_time")
    @classmethod
    def _check_daily_time(cls, v: str) -> str:
        try:
            hour, minute = v.split(":")
            if not (0 <= int(hour) <= 23 and 0 <= int(minute) <= 59):
                raise ValueError
        except ValueError as exc:  # pragma: no cover - 配置错误直接快速失败
            raise ValueError("DAILY_RUN_TIME 必须是 HH:MM 格式") from exc
        return f"{int(hour):02d}:{int(minute):02d}"

    # ---------- 便捷属性 ----------
    @property
    def repo_root(self) -> Path:
        return REPO_ROOT

    @property
    def workspace_path(self) -> Path:
        path = Path(self.workspace_dir)
        if not path.is_absolute():
            path = REPO_ROOT / path
        return path.resolve()

    @property
    def rss_feeds(self) -> list[str]:
        return [item.strip() for item in self.news_rss_feeds.split(",") if item.strip()]

    @property
    def enabled_channels(self) -> list[str]:
        return [item.strip().lower() for item in self.push_channels.split(",") if item.strip()]

    @property
    def is_mock_llm(self) -> bool:
        return self.llm_mode == "mock"


@lru_cache(maxsize=1)
def get_settings() -> Settings:
    """进程内单例配置；测试中可用 get_settings.cache_clear() 重置。"""
    return Settings()
