"""新闻服务门面：把数据源、缓存、去重与正文抽取组合给工具层使用。"""

from __future__ import annotations

import re
import time
from datetime import UTC, datetime

import httpx

from app.config import Settings
from app.news.dedup import normalize_url
from app.news.extractor import Article, fetch_article
from app.news.sources import FeedItem, bing_news_search, fetch_feed, filter_recent

CACHE_TTL_SECONDS = 300


def _query_tokens(query: str) -> list[str]:
    tokens = [token for token in re.split(r"[\s,，、;；/|]+", query or "") if token]
    # 中文查询常见整句，保留原串作为 token 之一；英文保留单词
    whole = (query or "").strip()
    if whole and whole not in tokens:
        tokens.insert(0, whole)
    return [token.lower() for token in tokens if len(token) >= 1][:8]


class NewsService:
    """对工具暴露 ``search`` / ``fetch`` 两个方法，内部做进程内缓存。"""

    def __init__(self, settings: Settings, client: httpx.Client | None = None) -> None:
        self.settings = settings
        self._client = client
        self._feed_cache: dict[str, tuple[float, list[FeedItem]]] = {}
        self._search_cache: dict[str, tuple[float, list[FeedItem]]] = {}

    # ------------------------------------------------------------------
    def _feed_items(self, feed_url: str, limit: int) -> list[FeedItem]:
        cached = self._feed_cache.get(feed_url)
        now = time.monotonic()
        if cached and now - cached[0] < CACHE_TTL_SECONDS:
            return cached[1]
        items = fetch_feed(feed_url, limit=limit, client=self._client)
        self._feed_cache[feed_url] = (now, items)
        return items

    def _bing_items(self, query: str, limit: int) -> list[FeedItem]:
        if not self.settings.news_bing_enabled:
            return []
        cache_key = f"bing::{query}::{limit}"
        cached = self._search_cache.get(cache_key)
        now = time.monotonic()
        if cached and now - cached[0] < CACHE_TTL_SECONDS:
            return cached[1]
        items = bing_news_search(
            query,
            limit=limit,
            lang=self.settings.news_language,
            endpoint=self.settings.news_bing_endpoint,
            client=self._client,
        )
        self._search_cache[cache_key] = (now, items)
        return items

    # ------------------------------------------------------------------
    def search(self, query: str, days: int = 2, limit: int = 8) -> list[FeedItem]:
        """先按 query 走 Bing News RSS，再在固定 RSS 源里做关键词匹配，合并去重。"""
        limit = max(1, min(limit, 20))
        try:
            days = max(1, min(days, 14))
        except (TypeError, ValueError):
            days = 2

        tokens = _query_tokens(query)
        merged: list[FeedItem] = []
        seen: set[str] = set()

        def add(item: FeedItem) -> None:
            key = normalize_url(item.url) or item.url
            if key and key not in seen:
                seen.add(key)
                merged.append(item)

        for item in self._bing_items(query, limit=limit):
            add(item)

        if merged and len(merged) < limit:
            for item in self._bing_items(f"{query} AI", limit=limit):
                add(item)

        # 固定 RSS 源：仅保留与 query token 匹配的条目
        for feed_url in self.settings.rss_feeds:
            for item in self._feed_items(feed_url, limit=self.settings.news_max_articles):
                haystack = f"{item.title} {item.summary}".lower()
                if tokens and not any(token in haystack for token in tokens):
                    continue
                add(item)

        merged = filter_recent(merged, days=days)
        merged.sort(key=lambda item: item.published_at or "", reverse=True)
        return merged[:limit]

    # ------------------------------------------------------------------
    def fetch(self, url: str, max_chars: int = 4000) -> Article:
        return fetch_article(url, max_chars=max_chars, client=self._client)

    def close(self) -> None:
        if self._client is not None:
            self._client.close()

    @staticmethod
    def now_iso() -> str:
        return datetime.now(UTC).isoformat()
