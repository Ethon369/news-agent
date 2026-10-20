"""API DTO、统一返回信封与 ORM → dict 序列化。"""

from __future__ import annotations

import json
from datetime import UTC, date, datetime
from typing import Any

from pydantic import BaseModel, Field, field_validator

# ---------------------------------------------------------------------------
# 统一返回信封
# ---------------------------------------------------------------------------

CODE_OK = 0
CODE_BAD_REQUEST = 40001
CODE_NOT_FOUND = 40401
CODE_CONFLICT = 40901
CODE_INTERNAL = 50001
CODE_LLM_UNAVAILABLE = 50301


def ok(data: Any = None) -> dict[str, Any]:
    return {"code": CODE_OK, "message": "ok", "data": data}


def err(code: int, message: str) -> dict[str, Any]:
    return {"code": code, "message": message, "data": None}


class ApiException(Exception):
    """业务异常，由全局异常处理器转成统一信封。"""

    def __init__(self, code: int, message: str, http_status: int = 400) -> None:
        super().__init__(message)
        self.code = code
        self.message = message
        self.http_status = http_status


# ---------------------------------------------------------------------------
# 请求模型
# ---------------------------------------------------------------------------


class UserCreate(BaseModel):
    name: str = Field(min_length=1, max_length=80)
    email: str | None = Field(default=None, max_length=255)
    timezone: str = Field(default="Asia/Shanghai", max_length=64)

    @field_validator("name")
    @classmethod
    def _strip_name(cls, v: str) -> str:
        v = v.strip()
        if not v:
            raise ValueError("name 不能为空")
        return v

    @field_validator("email")
    @classmethod
    def _strip_email(cls, v: str | None) -> str | None:
        if v is None:
            return None
        v = v.strip()
        if not v:
            return None
        if "@" not in v:
            raise ValueError("email 格式不正确")
        return v


class SubscriptionUpdate(BaseModel):
    topics: list[str] | None = None
    keywords: list[str] | None = None
    exclude_keywords: list[str] | None = None
    max_items: int | None = Field(default=None, ge=3, le=10)
    language: str | None = Field(default=None, max_length=16)
    channels: list[str] | None = None
    push_time: str | None = None
    enabled: bool | None = None

    @field_validator("channels")
    @classmethod
    def _check_channels(cls, v: list[str] | None) -> list[str] | None:
        if v is None:
            return None
        allowed = {"web", "feishu", "email"}
        cleaned = [c.strip().lower() for c in v if c.strip()]
        bad = [c for c in cleaned if c not in allowed]
        if bad:
            raise ValueError(f"不支持的推送渠道: {bad}，可选 web/feishu/email")
        return cleaned or ["web"]

    @field_validator("push_time")
    @classmethod
    def _check_push_time(cls, v: str | None) -> str | None:
        if v is None:
            return None
        try:
            hour, minute = v.split(":")
            if not (0 <= int(hour) <= 23 and 0 <= int(minute) <= 59):
                raise ValueError
        except ValueError:
            raise ValueError("push_time 必须是 HH:MM 格式") from None
        return f"{int(hour):02d}:{int(minute):02d}"

    @field_validator("topics", "keywords", "exclude_keywords")
    @classmethod
    def _clean_str_list(cls, v: list[str] | None) -> list[str] | None:
        if v is None:
            return None
        return [item.strip() for item in v if item and item.strip()]


class RunCreate(BaseModel):
    mock: bool = False


# ---------------------------------------------------------------------------
# 序列化工具
# ---------------------------------------------------------------------------


def iso(value: datetime | date | None) -> str | None:
    if value is None:
        return None
    if isinstance(value, datetime):
        if value.tzinfo is None:
            value = value.replace(tzinfo=UTC)
        return value.isoformat()
    return value.isoformat()


def parse_json_list(raw: str | None) -> list[str]:
    if not raw:
        return []
    try:
        data = json.loads(raw)
    except (TypeError, ValueError):
        return []
    return [str(item) for item in data] if isinstance(data, list) else []


def dump_json_list(items: list[str]) -> str:
    return json.dumps(items, ensure_ascii=False)


def subscription_to_dict(sub) -> dict[str, Any] | None:
    if sub is None:
        return None
    return {
        "topics": parse_json_list(sub.topics),
        "keywords": parse_json_list(sub.keywords),
        "exclude_keywords": parse_json_list(sub.exclude_keywords),
        "max_items": sub.max_items,
        "language": sub.language,
        "channels": parse_json_list(sub.channels),
        "push_time": sub.push_time,
        "enabled": bool(sub.enabled),
    }


def user_to_dict(user) -> dict[str, Any]:
    return {
        "id": user.id,
        "name": user.name,
        "email": user.email,
        "timezone": user.timezone,
        "created_at": iso(user.created_at),
        "subscription": subscription_to_dict(user.subscription),
    }


def briefing_summary_to_dict(briefing) -> dict[str, Any]:
    return {
        "id": briefing.id,
        "title": briefing.title,
        "summary": briefing.summary,
        "item_count": briefing.item_count,
        "briefing_date": iso(briefing.briefing_date),
        "created_at": iso(briefing.created_at),
    }


def briefing_item_to_dict(item) -> dict[str, Any]:
    return {
        "rank": item.rank,
        "title": item.title,
        "url": item.url,
        "source": item.source,
        "published_at": item.published_at,
        "summary": item.summary,
        "reason": item.reason,
        "evidence_level": item.evidence_level,
        "tags": parse_json_list(item.tags),
        "score": item.score,
    }


def briefing_detail_to_dict(briefing, deliveries: list | None = None) -> dict[str, Any]:
    data = briefing_summary_to_dict(briefing)
    data.update(
        {
            "content_md": briefing.content_md,
            "items": [briefing_item_to_dict(item) for item in briefing.items],
            "deliveries": [
                {
                    "channel": d.channel,
                    "status": d.status,
                    "detail": d.detail,
                    "created_at": iso(d.created_at),
                }
                for d in (deliveries or [])
            ],
        }
    )
    return data


def step_to_dict(step) -> dict[str, Any]:
    return {
        "step_index": step.step_index,
        "kind": step.kind,
        "thought": step.thought,
        "tool_name": step.tool_name,
        "tool_args": step.tool_args,
        "tool_result": step.tool_result,
        "duration_ms": step.duration_ms,
        "created_at": iso(step.created_at),
    }


def run_to_dict(run, include_steps: bool = True) -> dict[str, Any]:
    data = {
        "id": run.id,
        "user_id": run.user_id,
        "status": run.status,
        "trigger": run.trigger,
        "llm_mode": run.llm_mode,
        "model": run.model,
        "step_count": run.step_count,
        "tool_call_count": run.tool_call_count,
        "prompt_tokens": run.prompt_tokens,
        "completion_tokens": run.completion_tokens,
        "briefing_id": run.briefing_id,
        "error": run.error,
        "started_at": iso(run.started_at),
        "finished_at": iso(run.finished_at),
    }
    if include_steps:
        data["steps"] = [step_to_dict(step) for step in run.steps]
    return data


def run_summary_to_dict(run) -> dict[str, Any]:
    return run_to_dict(run, include_steps=False)
