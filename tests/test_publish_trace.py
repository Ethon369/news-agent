"""链接溯源与证据分级测试（吸收自对比项目的核心不变量）。"""

from __future__ import annotations

from app.tools.publish_tool import (
    EVIDENCE_BODY,
    EVIDENCE_SUMMARY,
    EVIDENCE_TITLE,
    _publish_handler,
    validate_payload,
)


def _payload(*urls: str) -> dict:
    return {
        "title": "AI Daily · 测试",
        "summary": "总览",
        "items": [
            {"title": f"新闻{i + 1}", "url": url, "summary": "摘要", "source": "Demo"} for i, url in enumerate(urls)
        ],
    }


def test_url_must_come_from_collected_set():
    """核心不变量：模型不能编造/引用本次运行没采集过的链接。"""
    collected = {"https://example.com/real-1", "https://example.com/real-2"}
    payload, error = validate_payload(
        _payload("https://example.com/real-1", "https://evil.example/fake"),
        committed_urls=collected,
    )
    assert payload is None
    assert "不在本次运行已采集的链接中" in error


def test_url_normalization_allows_tracking_variants():
    """同一链接带 utm 参数应视为已采集（否则会误杀正常运行）。"""
    payload, error = validate_payload(
        _payload("https://example.com/real-1?utm_source=newsletter"),
        committed_urls={"https://example.com/real-1"},
    )
    assert error == ""
    assert payload is not None
    assert len(payload["items"]) == 1


def test_evidence_levels():
    payload, error = validate_payload(
        _payload(
            "https://example.com/fetched",
            "https://example.com/summary-only",
            "https://example.com/title-only",
        ),
        committed_urls={
            "https://example.com/fetched",
            "https://example.com/summary-only",
            "https://example.com/title-only",
        },
        fetched_urls={"https://example.com/fetched"},
    )
    assert error == ""
    levels = [item["evidence_level"] for item in payload["items"]]
    assert levels[0] == EVIDENCE_BODY
    assert levels[1] == EVIDENCE_SUMMARY
    assert levels[2] == EVIDENCE_SUMMARY  # 有摘要字段即算「仅来源摘要」


def test_title_only_evidence():
    payload, error = validate_payload(
        {
            "title": "t",
            "items": [{"title": "只有标题", "url": "https://example.com/t", "summary": ""}],
        },
        committed_urls={"https://example.com/t"},
    )
    assert error == ""
    assert payload["items"][0]["evidence_level"] == EVIDENCE_TITLE


def test_publish_handler_requires_collected_news(tool_ctx):
    tool_ctx.committed_urls = []
    result = _publish_handler(_payload("https://example.com/x"), tool_ctx)
    assert not result.ok
    assert result.code == "no_news_collected"


def test_publish_handler_rejects_fabricated_url(tool_ctx):
    tool_ctx.committed_urls = ["https://example.com/demo/1"]
    result = _publish_handler(_payload("https://made-up.example/news"), tool_ctx)
    assert not result.ok
    assert result.code == "invalid_briefing"
    assert "禁止编造" in result.content or "已采集" in result.content


def test_publish_handler_marks_fetched_evidence(tool_ctx):
    tool_ctx.committed_urls = ["https://example.com/demo/1"]
    tool_ctx.mark_fetched("https://example.com/demo/1")
    result = _publish_handler(_payload("https://example.com/demo/1"), tool_ctx)
    assert result.ok
    assert tool_ctx.briefing_payload is not None
    assert tool_ctx.briefing_payload["items"][0]["evidence_level"] == EVIDENCE_BODY
