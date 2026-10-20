"""推送通道测试：web / feishu / email。"""

from __future__ import annotations

from types import SimpleNamespace

import httpx
import pytest
import respx

from app.notify.email import EmailNotifier
from app.notify.feishu import FeishuNotifier
from app.notify.web import WebNotifier


def _fake_briefing():
    item = SimpleNamespace(
        title="演示新闻",
        source="Demo",
        url="https://example.com/1",
        reason="命中偏好",
        published_at="2026-10-20T08:00:00+00:00",
    )
    return SimpleNamespace(title="AI Daily · 测试", summary="总览", items=[item])


def _user(name: str = "用户", email: str | None = "a@b.com"):
    return SimpleNamespace(name=name, email=email)


def test_web_notifier_always_succeeds(test_settings):
    result = WebNotifier(test_settings).send(_fake_briefing(), _user())
    assert result.status == "success"


def test_feishu_skipped_without_webhook(test_settings):
    result = FeishuNotifier(test_settings).send(_fake_briefing(), _user())
    assert result.status == "skipped"


@respx.mock
def test_feishu_success(test_settings):
    settings = test_settings.model_copy(update={"feishu_webhook_url": "https://open.feishu.cn/webhook/test"})
    respx.post("https://open.feishu.cn/webhook/test").mock(return_value=httpx.Response(200, json={"code": 0}))
    result = FeishuNotifier(settings).send(_fake_briefing(), _user())
    assert result.status == "success"


@respx.mock
def test_feishu_failure_is_reported(test_settings):
    settings = test_settings.model_copy(update={"feishu_webhook_url": "https://open.feishu.cn/webhook/bad"})
    respx.post("https://open.feishu.cn/webhook/bad").mock(
        return_value=httpx.Response(200, json={"code": 19021, "msg": "sign match fail"})
    )
    result = FeishuNotifier(settings).send(_fake_briefing(), _user())
    assert result.status == "failed"
    assert "19021" in result.detail


def test_feishu_network_error_is_caught(test_settings):
    settings = test_settings.model_copy(update={"feishu_webhook_url": "https://open.feishu.cn/webhook/err"})
    with respx.mock:
        respx.post("https://open.feishu.cn/webhook/err").mock(side_effect=httpx.ConnectError("boom"))
        result = FeishuNotifier(settings).send(_fake_briefing(), _user())
    assert result.status == "failed"


def test_email_skipped_without_config(test_settings):
    result = EmailNotifier(test_settings).send(_fake_briefing(), _user())
    assert result.status == "skipped"


def test_email_skipped_without_user_email(test_settings):
    settings = test_settings.model_copy(
        update={"smtp_host": "smtp.example.com", "smtp_user": "u", "smtp_password": "p"}
    )
    result = EmailNotifier(settings).send(_fake_briefing(), _user(email=None))
    assert result.status == "skipped"


def test_email_html_escapes_llm_content():
    """AI code review 发现的 P2：LLM 生成的文本进入邮件 HTML 前必须转义。"""
    from datetime import date

    from app.notify.email import render_email_html

    item = SimpleNamespace(
        title="<script>alert(1)</script>",
        source="Demo",
        url="javascript:alert(1)",
        reason="",
        published_at=None,
        summary="<img src=x onerror=alert(1)>",
        evidence_level="仅标题",
    )
    briefing = SimpleNamespace(
        title="<b>标题</b>", summary="<script>x</script>", items=[item], briefing_date=date(2026, 10, 20)
    )
    html = render_email_html(briefing, _user(name="<i>用户</i>"))
    assert "<script>" not in html
    assert "<img" not in html  # 标签被转义成文本，不再具有 HTML 语义
    assert "&lt;img" in html
    assert "javascript:" not in html
    assert html.count("&lt;") >= 3
    assert 'href="#"' in html  # 非 http(s) 链接被降级
    assert "&lt;i&gt;用户" in html
    assert "证据范围：仅标题" in html  # 证据分级进入邮件正文


def test_email_subject_uses_date_and_top_story():
    from datetime import date

    from app.notify.email import build_subject

    item = SimpleNamespace(title="MiniMax M3.1 Flash 发布")
    briefing = SimpleNamespace(title="AI Daily · 2026-10-20", items=[item], briefing_date=date(2026, 10, 20))
    subject = build_subject(briefing)
    assert subject.startswith("AI 每日简报｜10月20日：")
    assert "MiniMax M3.1 Flash 发布" in subject


def test_email_subject_without_items():
    from datetime import date

    from app.notify.email import build_subject

    briefing = SimpleNamespace(title="AI Daily · 2026-10-20", items=[], briefing_date=date(2026, 10, 20))
    assert build_subject(briefing) == "AI 每日简报｜10月20日：AI Daily · 2026-10-20"


@pytest.mark.parametrize("channels", [["web"], ["web", "feishu"]])
def test_build_notifiers(test_settings, channels):
    from app.notify import build_notifiers

    notifiers = build_notifiers(test_settings, channels)
    assert [notifier.channel for notifier in notifiers] == channels
