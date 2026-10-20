"""新闻数据源：Bing News RSS 搜索 + 固定 RSS 订阅源。

选择 RSS 的理由见 ADR-0005：免 API Key、官方结构化出口、评审 5 分钟可跑。
"""

from __future__ import annotations

import calendar
from dataclasses import dataclass, field
from datetime import UTC, datetime, timedelta
from urllib.parse import quote_plus

import feedparser
import httpx

USER_AGENT = "AIDailyAgent/0.1 (+https://github.com/; news briefing demo)"
DEFAULT_TIMEOUT = 20.0


@dataclass
class FeedItem:
    title: str
    url: str
    source: str = ""
    published_at: str | None = None
    summary: str = ""
    query: str = ""
    origin: str = "rss"  # rss | bing
    extra: dict = field(default_factory=dict)

    def to_dict(self) -> dict:
        return {
            "title": self.title,
            "url": self.url,
            "source": self.source,
            "published_at": self.published_at,
            "summary": self.summary,
            "origin": self.origin,
        }


def _entry_datetime(entry) -> datetime | None:
    for attr in ("published_parsed", "updated_parsed"):
        parsed = getattr(entry, attr, None)
        if parsed:
            try:
                return datetime.fromtimestamp(calendar.timegm(parsed), tz=UTC)
            except (OverflowError, ValueError):
                continue
    return None


def _clean_html(raw: str, limit: int = 320) -> str:
    """把 RSS 描述里的 HTML 粗略清成纯文本。"""
    import re

    text = re.sub(r"<script.*?</script>", " ", raw or "", flags=re.S | re.I)
    text = re.sub(r"<style.*?</style>", " ", text, flags=re.S | re.I)
    text = re.sub(r"<[^>]+>", " ", text)
    text = re.sub(r"&nbsp;?", " ", text)
    text = re.sub(r"&amp;", "&", text)
    text = re.sub(r"&lt;", "<", text)
    text = re.sub(r"&gt;", ">", text)
    text = re.sub(r"&#\d+;", " ", text)
    text = re.sub(r"\s+", " ", text).strip()
    return text[:limit]


def _parse_feed(content: bytes, origin: str, query: str = "", limit: int = 20) -> list[FeedItem]:
    parsed = feedparser.parse(content)
    items: list[FeedItem] = []
    for entry in parsed.entries[: limit * 2]:
        title = (getattr(entry, "title", "") or "").strip()
        link = (getattr(entry, "link", "") or "").strip()
        if not title or not link:
            continue
        published = _entry_datetime(entry)
        source = ""
        if origin == "bing":
            source_info = getattr(entry, "source", None)
            if isinstance(source_info, dict):
                source = (source_info.get("title") or "").strip()
        if not source:
            source = (parsed.feed.get("title") or "").strip() if hasattr(parsed, "feed") else ""
        summary = _clean_html(getattr(entry, "summary", "") or getattr(entry, "description", ""))
        items.append(
            FeedItem(
                title=title,
                url=link,
                source=source,
                published_at=published.isoformat() if published else None,
                summary=summary,
                query=query,
                origin=origin,
            )
        )
        if len(items) >= limit:
            break
    return items


def _looks_like_feed(content: bytes) -> bool:
    """粗校验响应确实是 RSS/Atom，而不是被重定向到首页的 HTML。"""
    head = (content or b"")[:600].lstrip().lower()
    return head.startswith(b"<?xml") or b"<rss" in head or b"<feed" in head


def _http_get(url: str, timeout: float = DEFAULT_TIMEOUT, client: httpx.Client | None = None) -> bytes:
    headers = {"User-Agent": USER_AGENT, "Accept": "application/rss+xml, application/xml, text/xml, */*"}
    if client is not None:
        response = client.get(url, headers=headers, timeout=timeout)
    else:
        with httpx.Client(follow_redirects=True) as own_client:
            response = own_client.get(url, headers=headers, timeout=timeout)
    response.raise_for_status()
    return response.content


def bing_news_search(
    query: str,
    limit: int = 8,
    lang: str = "zh-CN",
    endpoint: str = "https://www.bing.com/news/search",
    client: httpx.Client | None = None,
) -> list[FeedItem]:
    """用 Bing News 的 RSS 输出做新闻检索（无需 API Key）。

    注意：不要加 ``cc=CN`` 参数 —— 实测会 302 重定向到 Bing 首页（HTML），
    导致解析为空。这里只保留 ``format=rss`` 与 ``setlang``。
    """
    url = f"{endpoint}?q={quote_plus(query)}&format=rss&setlang={lang.split('-')[0]}"
    try:
        content = _http_get(url, client=client)
    except (httpx.HTTPError, OSError):
        return []
    if not _looks_like_feed(content):
        return []
    return _parse_feed(content, origin="bing", query=query, limit=limit)


def fetch_feed(
    feed_url: str,
    limit: int = 20,
    client: httpx.Client | None = None,
) -> list[FeedItem]:
    """抓取一个固定 RSS 源；失败/被重定向到 HTML 时返回空列表（单源失败不影响整体）。"""
    try:
        content = _http_get(feed_url, client=client)
    except (httpx.HTTPError, OSError):
        return []
    if not _looks_like_feed(content):
        return []
    return _parse_feed(content, origin="rss", limit=limit)


def filter_recent(items: list[FeedItem], days: int = 2, now: datetime | None = None) -> list[FeedItem]:
    """按发布时间过滤；无发布时间的条目保留（宁可多给模型判断）。"""
    now = now or datetime.now(UTC)
    cutoff = now - timedelta(days=max(days, 1))
    kept = []
    for item in items:
        if not item.published_at:
            kept.append(item)
            continue
        try:
            published = datetime.fromisoformat(item.published_at)
            if published.tzinfo is None:
                published = published.replace(tzinfo=UTC)
        except ValueError:
            kept.append(item)
            continue
        if published >= cutoff:
            kept.append(item)
    return kept
