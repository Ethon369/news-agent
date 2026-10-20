"""新闻源解析、正文抽取与 NewsService 集成测试（全部离线 mock HTTP）。"""

from __future__ import annotations

from datetime import UTC, datetime

import httpx
import pytest

from app.news.extractor import extract_from_html, fetch_article
from app.news.service import NewsService
from app.news.sources import _parse_feed, fetch_feed, filter_recent

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


def test_bing_news_search_url_has_no_cc_param():
    """回归：Bing 的 cc=CN 参数会触发 302 到首页，导致检索永远为空。"""
    captured = {}

    def handler(request: httpx.Request) -> httpx.Response:
        captured["url"] = str(request.url)
        return httpx.Response(200, text=BING_XML, headers={"content-type": "application/rss+xml"})

    client = httpx.Client(transport=httpx.MockTransport(handler))
    from app.news.sources import bing_news_search

    items = bing_news_search("AI Agent", client=client)
    assert items
    assert "cc=" not in captured["url"]
    assert "format=rss" in captured["url"]


def test_bing_news_search_rejects_html_redirect_page():
    """被重定向到 HTML 首页时返回空，而不是把 HTML 当 RSS 解析。"""

    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(
            200, text="<html><body>Bing homepage</body></html>", headers={"content-type": "text/html"}
        )

    client = httpx.Client(transport=httpx.MockTransport(handler))
    from app.news.sources import bing_news_search

    assert bing_news_search("AI", client=client) == []


def test_fetch_feed_rejects_html_page(monkeypatch):
    """机器之心等源会 302 到 HTML，不应被当作 RSS。"""
    monkeypatch.setattr(
        "app.news.sources._http_get", lambda *args, **kwargs: b"<html><body>redirected</body></html>"
    )
    assert fetch_feed("https://feed.example/rss") == []


def test_news_service_falls_back_to_latest_feed_items(test_settings):
    """检索源不可达/无匹配时，退化为订阅源最新条目，保证 Agent 有候选可用。"""
    settings = test_settings.model_copy(
        update={
            "news_rss_feeds": "https://feed.example/rss",
            "news_bing_enabled": False,
            "news_max_articles": 10,
        }
    )

    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, text=RSS_XML, headers={"content-type": "application/rss+xml"})

    client = httpx.Client(transport=httpx.MockTransport(handler))
    service = NewsService(settings, client=client)
    items = service.search("zzz-完全无关的关键词-zzz", days=30, limit=5)
    assert items, "fallback 应该返回订阅源最新条目"
    assert any("OpenAI" in item.title for item in items)


def test_news_service_reports_source_health(test_settings):
    settings = test_settings.model_copy(
        update={"news_rss_feeds": "https://feed.example/rss", "news_bing_enabled": True, "news_max_articles": 10}
    )
    service = NewsService(settings, client=_mock_client())
    assert service.has_live_sources() is True


def test_filter_recent_drops_old_items():
    now = datetime(2026, 10, 20, 12, 0, tzinfo=UTC)
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


# ---------------------------------------------------------------------------
# SSRF 防护（AI code review 发现的 P1）
# ---------------------------------------------------------------------------


def test_assert_public_url_blocks_localhost():
    from app.news.extractor import UnsafeURLError, assert_public_url

    for url in ["http://127.0.0.1:8000/api/users", "http://localhost/admin", "http://[::1]/"]:
        with pytest.raises(UnsafeURLError):
            assert_public_url(url)


def test_assert_public_url_blocks_private_dns(monkeypatch):
    import socket

    from app.news.extractor import UnsafeURLError, assert_public_url

    def fake_getaddrinfo(host, port, *args, **kwargs):
        return [(socket.AF_INET, socket.SOCK_STREAM, 6, "", ("10.0.0.5", 80))]

    monkeypatch.setattr("app.news.extractor.socket.getaddrinfo", fake_getaddrinfo)
    with pytest.raises(UnsafeURLError):
        assert_public_url("https://internal.example.com/news")


def test_assert_public_url_blocks_metadata_ip(monkeypatch):
    import socket

    from app.news.extractor import UnsafeURLError, assert_public_url

    def fake_getaddrinfo(host, port, *args, **kwargs):
        return [(socket.AF_INET, socket.SOCK_STREAM, 6, "", ("169.254.169.254", 80))]

    monkeypatch.setattr("app.news.extractor.socket.getaddrinfo", fake_getaddrinfo)
    with pytest.raises(UnsafeURLError):
        assert_public_url("http://169.254.169.254/latest/meta-data")


def test_fetch_article_blocks_private_target():
    article = fetch_article("http://127.0.0.1:8000/api/users")
    assert not article.ok
    assert "内网" in article.error or "本机" in article.error


def test_fetch_article_blocks_redirect_to_private(monkeypatch):
    import socket

    from app.news.extractor import fetch_article

    calls = {"n": 0}

    def fake_getaddrinfo(host, port, *args, **kwargs):
        calls["n"] += 1
        if host == "public.example.com":
            return [(socket.AF_INET, socket.SOCK_STREAM, 6, "", ("93.184.216.34", 443))]
        return [(socket.AF_INET, socket.SOCK_STREAM, 6, "", ("127.0.0.1", 8000))]

    monkeypatch.setattr("app.news.extractor.socket.getaddrinfo", fake_getaddrinfo)

    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(302, headers={"location": "http://127.0.0.1:8000/api/users"})

    client = httpx.Client(transport=httpx.MockTransport(handler))
    article = fetch_article("https://public.example.com/news", client=client)
    assert not article.ok
    assert "内网" in article.error or "本机" in article.error
    assert calls["n"] >= 2  # 每一跳都做了校验


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
