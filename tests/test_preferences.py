"""偏好匹配、去重过滤与简报渲染测试。"""

from __future__ import annotations

from app.services.briefing import match_item, normalize_items, render_markdown

PREFS = {
    "topics": ["AI Agent", "开源模型"],
    "keywords": ["MCP", "DeepSeek"],
    "exclude_keywords": ["招聘"],
    "max_items": 3,
}


def test_keyword_hit_increases_score():
    base = match_item({"title": "普通新闻", "summary": "与偏好无关"}, PREFS)
    hit = match_item({"title": "MCP 协议新进展", "summary": "AI Agent 生态"}, PREFS)
    assert hit.score > base.score
    assert any("MCP" in reason for reason in hit.reasons)


def test_exclude_keyword_drops_item():
    result = match_item({"title": "AI 公司招聘启事", "summary": "招 AI 工程师"}, PREFS)
    assert result.excluded
    assert result.excluded_by == "招聘"


def test_topic_hit_is_explained():
    result = match_item({"title": "开源模型生态观察", "summary": "社区动态"}, PREFS)
    assert any("话题" in reason for reason in result.reasons)


def test_normalize_items_dedupes_and_caps():
    items = [
        {"title": "A", "url": "https://example.com/1?utm_source=x", "summary": "MCP 相关"},
        {"title": "A2", "url": "https://example.com/1", "summary": "重复链接"},
        {"title": "B", "url": "https://example.com/2", "summary": "普通"},
        {"title": "C", "url": "https://example.com/3", "summary": "无关"},
        {"title": "D", "url": "https://example.com/4", "summary": "被排除 招聘"},
        {"title": "E", "url": "https://example.com/5", "summary": "MCP 再次命中"},
    ]
    kept, dropped = normalize_items(items, PREFS, known_urls=set())
    assert len(kept) <= PREFS["max_items"]
    urls = [item["url"] for item in kept]
    assert "https://example.com/4" not in urls
    assert len(dropped) >= 2


def test_normalize_items_drops_known_urls():
    items = [{"title": "旧闻", "url": "https://example.com/old"}]
    kept, dropped = normalize_items(items, PREFS, known_urls={"https://example.com/old"})
    assert kept == []
    assert dropped and "重复" in dropped[0]["drop_reason"]


def test_render_markdown_contains_links_and_reason():
    items = [
        {
            "title": "标题一",
            "url": "https://example.com/a",
            "source": "Demo",
            "published_at": "2026-10-20T08:00:00+00:00",
            "summary": "摘要内容",
            "reason": "命中关键词 MCP",
            "tags": ["MCP"],
        }
    ]
    markdown = render_markdown("AI Daily · 测试", "总览", items, "测试用户")
    assert "# AI Daily · 测试" in markdown
    assert "https://example.com/a" in markdown
    assert "命中关键词 MCP" in markdown
    assert "测试用户" in markdown
