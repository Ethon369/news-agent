"""配置校验测试：密钥走环境变量、配置错误要快速失败。"""

from __future__ import annotations

import pytest
from pydantic import ValidationError

from app.config import Settings


def test_llm_mode_must_be_known():
    with pytest.raises(ValidationError):
        Settings(llm_mode="turbo")


def test_daily_run_time_normalized():
    settings = Settings(daily_run_time="8:5")
    assert settings.daily_run_time == "08:05"


def test_daily_run_time_invalid():
    with pytest.raises(ValidationError):
        Settings(daily_run_time="25:99")


def test_rss_feeds_and_channels_parsing():
    settings = Settings(
        news_rss_feeds=" https://a.com/rss , https://b.com/rss ,, ",
        push_channels="web, feishu",
    )
    assert settings.rss_feeds == ["https://a.com/rss", "https://b.com/rss"]
    assert settings.enabled_channels == ["web", "feishu"]


def test_workspace_path_is_absolute():
    settings = Settings(workspace_dir="./workspace")
    assert settings.workspace_path.is_absolute()


def test_mock_mode_flag():
    assert Settings(llm_mode="mock").is_mock_llm
    assert not Settings(llm_mode="real", llm_api_key="x").is_mock_llm
