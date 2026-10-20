"""新闻模块：数据源、正文抽取、去重与统一服务门面。"""

from app.news.dedup import Deduplicator, normalize_title, normalize_url
from app.news.extractor import fetch_article
from app.news.service import NewsService
from app.news.sources import FeedItem, bing_news_search, fetch_feed

__all__ = [
    "Deduplicator",
    "FeedItem",
    "NewsService",
    "bing_news_search",
    "fetch_article",
    "fetch_feed",
    "normalize_title",
    "normalize_url",
]
