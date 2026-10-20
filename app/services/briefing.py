"""简报业务：偏好打分/过滤、Markdown 渲染、落库与历史摘要。

这一层是「纯业务」，不依赖 LLM 与网络，因此可以被大量单测覆盖。
"""

from __future__ import annotations

import json
import re
from dataclasses import dataclass, field
from datetime import date, datetime
from typing import Any

from sqlalchemy.orm import Session

from app.models import Briefing, BriefingItem, User, utcnow

MAX_HISTORY_FOR_PROMPT = 5


# ---------------------------------------------------------------------------
# 偏好匹配与打分
# ---------------------------------------------------------------------------


@dataclass
class MatchResult:
    score: float
    reasons: list[str] = field(default_factory=list)
    excluded: bool = False
    excluded_by: str = ""


def _split_terms(values: list[str]) -> list[str]:
    """拆分并保留原始大小写（用于展示），匹配时再 lower。"""
    terms: list[str] = []
    for value in values or []:
        for part in re.split(r"[,，、;；/|]+", str(value)):
            part = part.strip()
            if part:
                terms.append(part)
    return terms


def match_item(item: dict[str, Any], preferences: dict[str, Any]) -> MatchResult:
    """按关键词/话题给候选新闻打分；命中排除词直接淘汰。"""
    haystack = f"{item.get('title', '')} {item.get('summary', '')}".lower()
    reasons: list[str] = []
    score = 0.3

    exclude_terms = _split_terms(preferences.get("exclude_keywords") or [])
    for term in exclude_terms:
        if term and term.lower() in haystack:
            return MatchResult(score=0.0, excluded=True, excluded_by=term)

    for term in _split_terms(preferences.get("keywords") or []):
        if term and term.lower() in haystack:
            score += 0.25
            reasons.append(f"命中关键词「{term}」")

    topic_hits = 0
    for topic in preferences.get("topics") or []:
        topic_lower = str(topic).strip().lower()
        if not topic_lower:
            continue
        tokens = [token for token in re.split(r"[\s/]+", topic_lower) if token]
        if topic_lower in haystack or any(token in haystack for token in tokens if len(token) >= 2):
            topic_hits += 1
            reasons.append(f"命中话题「{topic}」")

    if not reasons:
        reasons.append("与订阅话题的一般相关性")

    score += min(topic_hits, 3) * 0.15
    return MatchResult(score=round(min(score, 1.0), 4), reasons=reasons)


def normalize_items(
    payload_items: list[dict[str, Any]],
    preferences: dict[str, Any],
    known_urls: set[str],
) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    """对模型提交的条目做偏好过滤与去重，返回 (保留, 丢弃)。"""
    from app.news.dedup import normalize_url

    kept: list[dict[str, Any]] = []
    dropped: list[dict[str, Any]] = []
    seen: set[str] = set()
    max_items = int(preferences.get("max_items") or 5)

    for raw in payload_items:
        url_key = normalize_url(str(raw.get("url", "")))
        if url_key and (url_key in known_urls or url_key in seen):
            dropped.append({**raw, "drop_reason": "与历史简报或本次条目重复"})
            continue
        match = match_item(raw, preferences)
        if match.excluded:
            dropped.append({**raw, "drop_reason": f"命中排除关键词「{match.excluded_by}」"})
            continue
        seen.add(url_key)
        kept.append(
            {
                **raw,
                "score": raw.get("score") if raw.get("score") is not None else match.score,
                "reason": raw.get("reason") or "；".join(match.reasons[:2]),
                "tags": raw.get("tags") or [],
            }
        )

    return kept[:max_items], dropped


# ---------------------------------------------------------------------------
# Markdown 渲染
# ---------------------------------------------------------------------------


def render_markdown(title: str, summary: str, items: list[dict[str, Any]], user_name: str) -> str:
    lines = [f"# {title}", ""]
    if summary:
        lines += [f"> {summary}", ""]
    lines += [f"共 {len(items)} 条 · 为 {user_name} 定制", ""]
    for index, item in enumerate(items, start=1):
        published = (item.get("published_at") or "").replace("T", " ")[:16]
        source = item.get("source") or "未知来源"
        meta = f"{source}" + (f" · {published}" if published else "")
        lines.append(f"## {index}. {item.get('title', '')}")
        lines.append("")
        if item.get("summary"):
            lines.append(str(item["summary"]))
            lines.append("")
        lines.append(f"- 来源：{meta}")
        lines.append(f"- 链接：{item.get('url', '')}")
        if item.get("evidence_level"):
            lines.append(f"- 证据范围：{item['evidence_level']}")
        if item.get("reason"):
            lines.append(f"- 入选理由：{item['reason']}")
        if item.get("tags"):
            lines.append(f"- 标签：{'、'.join(str(tag) for tag in item['tags'])}")
        lines.append("")
    lines.append("---")
    lines.append("由 AI Daily Agent 基于 LLM 自主工具调用生成；每条均标注原始来源链接与证据范围。")
    return "\n".join(lines)


# ---------------------------------------------------------------------------
# 落库与历史
# ---------------------------------------------------------------------------


def persist_briefing(
    session: Session,
    *,
    user: User,
    run_id: int | None,
    title: str,
    summary: str,
    items: list[dict[str, Any]],
    preferences: dict[str, Any],
    briefing_date: date | None = None,
    dropped: list[dict[str, Any]] | None = None,
) -> Briefing:
    today = briefing_date or date.today()
    content_md = render_markdown(title, summary, items, user.name)
    briefing = Briefing(
        user_id=user.id,
        run_id=run_id,
        title=title,
        summary=summary,
        content_md=content_md,
        item_count=len(items),
        briefing_date=today,
        created_at=utcnow(),
    )
    session.add(briefing)
    session.flush()  # 拿到 briefing.id

    for rank, item in enumerate(items, start=1):
        session.add(
            BriefingItem(
                briefing_id=briefing.id,
                rank=rank,
                title=str(item.get("title", ""))[:300],
                url=str(item.get("url", "")),
                source=str(item.get("source", "") or "")[:120],
                published_at=item.get("published_at"),
                summary=str(item.get("summary", "") or ""),
                reason=str(item.get("reason", "") or ""),
                evidence_level=str(item.get("evidence_level", "") or "")[:40],
                tags=json.dumps(item.get("tags") or [], ensure_ascii=False),
                score=item.get("score"),
            )
        )
    session.flush()
    return briefing


def recent_history(session: Session, user_id: int, limit: int = MAX_HISTORY_FOR_PROMPT) -> list[Briefing]:
    return session.query(Briefing).filter(Briefing.user_id == user_id).order_by(Briefing.id.desc()).limit(limit).all()


def history_lines(briefings: list[Briefing]) -> list[str]:
    lines = []
    for briefing in briefings:
        titles = "；".join(item.title for item in briefing.items[:6]) or "（无条目）"
        lines.append(f"- {briefing.briefing_date} {briefing.title}：{titles}")
    return lines


def known_urls(session: Session, user_id: int, limit: int = 200) -> set[str]:
    from app.news.dedup import normalize_url

    rows = (
        session.query(BriefingItem.url)
        .join(Briefing, Briefing.id == BriefingItem.briefing_id)
        .filter(Briefing.user_id == user_id)
        .order_by(BriefingItem.id.desc())
        .limit(limit)
        .all()
    )
    return {normalize_url(row[0]) for row in rows if row[0]}


def write_archive(workspace, briefing: Briefing) -> None:
    """把简报写入 workspace/archive/YYYY-MM-DD.md，供下次运行的 search_content 去重。"""
    archive_dir = workspace / "archive"
    archive_dir.mkdir(parents=True, exist_ok=True)
    day = briefing.briefing_date
    target = archive_dir / f"{day.isoformat()}.md"
    target.write_text(briefing.content_md, encoding="utf-8")


def write_archive_index(workspace, briefings: list[Briefing]) -> None:
    """维护 archive/index.md：让 Agent 用 read_file 一次读到历史主题与链接。

    这是「文件系统即记忆」的一部分：历史不只存数据库，也以 Agent 可读的
    文本形式存在工作区里，read_file / search_content 才有真实用途。
    """
    archive_dir = workspace / "archive"
    archive_dir.mkdir(parents=True, exist_ok=True)
    lines = ["# 历史简报索引", "", f"共 {len(briefings)} 份最近简报（新→旧）：", ""]
    for briefing in briefings:
        lines.append(f"## {briefing.briefing_date} · {briefing.title}")
        if briefing.summary:
            lines.append(f"> {briefing.summary}")
        for item in briefing.items[:8]:
            lines.append(f"- {item.title} | {item.url}")
        lines.append("")
    if not briefings:
        lines.append("（还没有历史简报，这是第一份）")
    (archive_dir / "index.md").write_text("\n".join(lines), encoding="utf-8")


def parse_history_date(value: datetime | date) -> date:
    return value.date() if isinstance(value, datetime) else value
