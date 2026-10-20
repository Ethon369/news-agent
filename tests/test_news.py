"""新闻源解析、正文抽取与 NewsService 集成测试（全部离线 mock HTTP）。"""

from __future__ import annotations

from datetime import datetime, timedelta, timezone

import httpx

from app.news.extractor import extract_from_html, fetch_article
from app.news.service import NewsService
from app.news.sources import fetch_feed, filter_recent, _parse_feed

RSS_XML = """<?xml version="1.0" encoding="UTF-8"?>
<rss version="2.0"><channel><title>Test Feed</title>
<item>
  <title>OpenAI 发布新模型</title>
  <link>https://example.com/news/1</link>
  <description>&lt;p&gt;这是一条&lt;b&gt;摘要&lt;/b&gt;内容&lt;/p&gt;</description>
  <pubDate>Mon, 20 Oct 2026 08:00:00 GMT</pubDate>
</item>
<item>
  <title>无关的体育新闻</title>
  <link>https://example.com/news/2</link>
  <description>体育内容</description>
  <pubDate>Mon, 20 Oct 2026 06:00:00 GMT</pubDate>
</item>
</channel></rss>
"""

BING_XML = """<?xml version="1.0" encoding="UTF-8"?>
<rss version="2.0"><channel><title>Bing News</title>
<item>
  <title>AI Agent 框架新版本发布</title>
  <link>https://example.com/bing/1</link>
  <description>Agent 框架更新内容</description>
  <pubDate>Mon, 20 Oct 2026 09:00:00 GMT</pubDate>
  <source>TechCrunch</source>
</item>
</channel></rss>
"""


def test_parse_feed_extracts_fields():
    items = _parse_feed(RSS_XML.encode("utf-8"), origin="rss", limit=10)
    assert len(items) == 2
    first = items[0]
    assert first.title == "OpenAI 发布新模型"
    assert first.url == "https://example.com/news/1"
    assert first.published_at is not None and first.published_at.startswith("2026-10-20")
    assert "<b>" not in first.summary  # HTML 被清洗


def test_fetch_feed_handles_network_failure(monkeypatch):
    monkeypatch.setattr("app.news.sources._http_get", lambda *args, **kwargs: (_ for _ in ()).throw(OSError("boom")))
    assert fetch_feed("https://feed.example/rss") == []


def test_filter_recent_drops_old_items():
    now = datetime(2026, 10, 20, 12, 0, tzinfo=timezone.utc)
    items = _parse_feed(RSS_XML.encode("utf-8"), origin="rss", limit=10)
    recent = filter_recent(items, days=2, now=now)
    assert all(item.title != "无关的体育新闻" or item.published_at for item in recent)


def test_extract_from_html_removes_scripts_and_boilerplate():
    html = """
    <html><head><title>页面标题</title>
    <meta property="og:title" content="OG 标题">
    <meta property="og:site_name" content="示例站"></head>
    <body>
      <nav>导航内容</nav>
      <article>
        <h1>正文标题</h1>
        <p>这是第一段正文，长度足够被保留下来用于摘要。</p>
        <p>Subscribe to our newsletter 这是广告段落应该被过滤掉。</p>
        <p>这是第二段正文，内容同样足够长，应该被保留。</p>
      </article>
      <script>var evil = 1;</script>
    </body></html>
    """
    article = extract_from_html(html, url="https://example.com/news")
    assert article.title == "OG 标题"
    assert article.site == "示例站"
    assert "第一段正文" in article.text
    assert "第二段正文" in article.text
    assert "evil" not in article.text
    assert "导航内容" not in article.text
    assert "newsletter" not in article.text.lower()


def test_fetch_article_rejects_non_http():
    article = fetch_article("file:///etc/passwd")
    assert not article.ok


def _mock_client() -> httpx.Client:
    def handler(request: httpx.Request) -> httpx.Response:
        url = str(request.url)
        if "bing.com" in url:
            return httpx.Response(200, text=BING_XML, headers={"content-type": "application/rss+xml"})
        return httpx.Response(200, text=RSS_XML, headers={"content-type": "application/rss+xml"})

    return httpx.Client(transport=httpx.MockTransport(handler))


def test_news_service_merges_bing_and_rss(test_settings):
    settings = test_settings.model_copy(
        update={"news_rss_feeds": "https://feed.example/rss", "news_bing_enabled": True, "news_max_articles": 10}
    )
    service = NewsService(settings, client=_mock_client())
    items = service.search("OpenAI", days=5, limit=10)
    titles = [item.title for item in items]
    assert "OpenAI 发布新模型" in titles  # 来自 RSS + query 命中
    assert "AI Agent 框架新版本发布" in titles  # 来自 Bing


def test_news_service_caches_repeated_calls(test_settings):
    settings = test_settings.model_copy(
        update={"news_rss_feeds": "https://feed.example/rss", "news_bing_enabled": True, "news_max_articles": 10}
    )
    calls = {"count": 0}

    def handler(request: httpx.Request) -> httpx.Response:
        calls["count"] += 1
        return httpx.Response(200, text=RSS_XML, headers={"content-type": "application/rss+xml"})

    client = httpx.Client(transport=httpx.MockTransport(handler))
    service = NewsService(settings, client=client)
    service.search("OpenAI", days=5, limit=5)
    first_count = calls["count"]
    service.search("OpenAI", days=5, limit=5)
    assert calls["count"] == first_count  # 第二次走缓存
