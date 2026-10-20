"""URL/标题去重测试。"""

from __future__ import annotations

from app.news.dedup import Deduplicator, normalize_title, normalize_url


def test_normalize_url_strips_tracking_and_fragment():
    url = "https://www.example.com/news/ai-agent/?utm_source=x&utm_medium=y&id=42#section"
    normalized = normalize_url(url)
    assert normalized == "https://example.com/news/ai-agent?id=42"


def test_normalize_url_handles_http_and_trailing_slash():
    assert normalize_url("http://example.com/a/") == normalize_url("https://www.example.com/a")


def test_normalize_title_removes_site_suffix_and_punctuation():
    assert normalize_title("OpenAI 发布新模型 - TechCrunch") == normalize_title("OpenAI 发布新模型 | 某站")


def test_deduplicator_detects_same_url_variants():
    dedup = Deduplicator(known_urls=["https://example.com/post?utm_source=a"])
    assert dedup.is_duplicate("https://www.example.com/post/")
    assert dedup.is_duplicate("https://example.com/post#top")


def test_deduplicator_detects_similar_titles():
    dedup = Deduplicator(known_titles=["DeepSeek 发布 V4 模型，推理能力大幅提升"])
    assert dedup.is_duplicate("https://other.com/x", "DeepSeek 发布 V4 模型，推理能力大幅提升！")


def test_deduplicator_allows_new_content():
    dedup = Deduplicator(known_urls=["https://example.com/a"], known_titles=["旧新闻标题"])
    assert not dedup.is_duplicate("https://example.com/b", "完全不同的新新闻标题内容")


def test_remember_updates_state():
    dedup = Deduplicator()
    assert not dedup.is_duplicate("https://example.com/new")
    dedup.remember("https://example.com/new", "一条新新闻")
    assert dedup.is_duplicate("https://example.com/new")
    assert dedup.known_url_count == 1
