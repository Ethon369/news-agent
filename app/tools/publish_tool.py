"""发布工具：publish_briefing —— Agent 提交最终简报的唯一出口。

设计取舍：
- 工具本身不直接写数据库，只做**结构校验**并写入 ``ToolContext.briefing_payload``；
  由服务层（runner）负责落库，保证工具层与持久化解耦、可单测；
- 参数非法时返回结构化错误，让模型自行修正（而不是抛异常终止运行）；
- 提交成功后循环立即收敛（run 结束），避免模型继续无意义调用。
"""

from __future__ import annotations

import json
from typing import Any

from app.tools.base import ToolContext, ToolResult, ToolSpec

MAX_ITEMS = 10
MIN_ITEMS = 1


def _clean_tags(raw: Any) -> list[str]:
    if isinstance(raw, str):
        raw = [part.strip() for part in raw.split(",")]
    if not isinstance(raw, list):
        return []
    return [str(tag).strip() for tag in raw if str(tag).strip()][:8]


def validate_payload(payload: dict[str, Any], max_items: int = 5) -> tuple[dict[str, Any] | None, str]:
    """校验并规范化模型提交的简报，返回 (payload, error)。"""
    if not isinstance(payload, dict):
        return None, "参数必须是对象"

    title = str(payload.get("title") or "").strip()
    if not title:
        return None, "title 不能为空"
    if len(title) > 200:
        title = title[:200]

    summary = str(payload.get("summary") or "").strip()
    raw_items = payload.get("items")
    if not isinstance(raw_items, list) or not raw_items:
        return None, "items 必须是非空数组，每项包含 title 与 url"

    items: list[dict[str, Any]] = []
    seen_urls: set[str] = set()
    for index, raw in enumerate(raw_items):
        if not isinstance(raw, dict):
            return None, f"items[{index}] 必须是对象"
        item_title = str(raw.get("title") or "").strip()
        url = str(raw.get("url") or "").strip()
        if not item_title:
            return None, f"items[{index}].title 不能为空"
        if not url.lower().startswith(("http://", "https://")):
            return None, f"items[{index}].url 必须是 http(s) 链接，收到: {url!r}"
        if url in seen_urls:
            continue
        seen_urls.add(url)
        items.append(
            {
                "title": item_title[:300],
                "url": url,
                "source": str(raw.get("source") or "").strip()[:120],
                "published_at": (str(raw.get("published_at")).strip() if raw.get("published_at") else None),
                "summary": str(raw.get("summary") or "").strip()[:1200],
                "reason": str(raw.get("reason") or "").strip()[:400],
                "tags": _clean_tags(raw.get("tags")),
                "score": _parse_score(raw.get("score")),
            }
        )

    if len(items) < MIN_ITEMS:
        return None, "去重后没有有效条目（items 不能全为空）"
    if len(items) > min(max_items, MAX_ITEMS):
        items = items[: min(max_items, MAX_ITEMS)]

    return {
        "title": title,
        "summary": summary[:1200],
        "items": items,
    }, ""


def _parse_score(raw: Any) -> float | None:
    try:
        return round(float(raw), 4) if raw is not None else None
    except (TypeError, ValueError):
        return None


def _publish_handler(args: dict, ctx: ToolContext) -> ToolResult:
    max_items = int(ctx.preferences.get("max_items") or 5)
    payload, error = validate_payload(args, max_items=max_items)
    if payload is None:
        return ToolResult.failure(f"简报校验失败：{error}。请修正参数后重新调用 publish_briefing。", "invalid_briefing")

    ctx.briefing_payload = payload
    ctx.extra["published"] = True
    preview = json.dumps({"title": payload["title"], "item_count": len(payload["items"])}, ensure_ascii=False)
    return ToolResult.success(
        f"简报已成功提交：{preview}。本次简报任务完成，不要继续调用工具，直接给用户一句结束语即可。",
        data={"item_count": len(payload["items"])},
    )


def publish_briefing_tool() -> ToolSpec:
    return ToolSpec(
        name="publish_briefing",
        description=(
            "提交最终简报（唯一出口）。必须在完成检索、核实与写作后调用一次；"
            "items 按重要性从高到低排序，每条必须包含真实来源链接与一句话摘要。"
        ),
        parameters={
            "type": "object",
            "properties": {
                "title": {"type": "string", "description": "简报标题，例如 'AI Daily · 2026-10-20'"},
                "summary": {"type": "string", "description": "2-3 句话的今日总览"},
                "items": {
                    "type": "array",
                    "description": "入选新闻列表（按重要性排序）",
                    "items": {
                        "type": "object",
                        "properties": {
                            "title": {"type": "string", "description": "新闻标题"},
                            "url": {"type": "string", "description": "真实来源链接（http/https）"},
                            "source": {"type": "string", "description": "来源站点名"},
                            "published_at": {"type": "string", "description": "发布时间（ISO8601，可空）"},
                            "summary": {"type": "string", "description": "基于正文的 1-2 句事实性摘要"},
                            "reason": {"type": "string", "description": "为什么选它（命中用户哪个偏好）"},
                            "tags": {"type": "array", "items": {"type": "string"}, "description": "标签"},
                        },
                        "required": ["title", "url"],
                    },
                },
            },
            "required": ["title", "items"],
            "additionalProperties": False,
        },
        handler=_publish_handler,
    )
