"""元信息接口：前端启动时读取一次，用于徽标/建议/可用渠道。"""

from __future__ import annotations

from fastapi import APIRouter, Depends

from app import __version__
from app.api.deps import get_settings_dep
from app.config import Settings
from app.schemas import ok

router = APIRouter(tags=["meta"])

TOPIC_SUGGESTIONS = [
    "AI Agent",
    "大模型",
    "开源模型",
    "算力芯片",
    "AI 编程",
    "多模态",
    "RAG 检索",
    "AI 应用",
]

NEWS_SOURCES = [
    "Bing News RSS",
    "Hacker News",
    "arXiv cs.AI",
    "TechCrunch AI",
    "机器之心",
]


@router.get("/health")
def health(settings: Settings = Depends(get_settings_dep)) -> dict:
    return ok({"status": "ok", "version": __version__, "llm_mode": settings.llm_mode})


@router.get("/meta")
def meta(settings: Settings = Depends(get_settings_dep)) -> dict:
    channels = ["web"]
    if settings.feishu_webhook_url:
        channels.append("feishu")
    if settings.smtp_host and settings.smtp_user:
        channels.append("email")
    return ok(
        {
            "version": __version__,
            "llm_mode": settings.llm_mode,
            "model": settings.llm_model if settings.llm_mode == "real" else "mock-model",
            "channels_available": channels,
            "topic_suggestions": TOPIC_SUGGESTIONS,
            "news_sources": NEWS_SOURCES,
            "daily_run_time": settings.daily_run_time,
        }
    )
