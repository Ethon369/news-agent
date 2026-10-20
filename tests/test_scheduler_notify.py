"""调度与推送测试。"""

from __future__ import annotations

from datetime import datetime, timezone
from types import SimpleNamespace

import httpx
import pytest
import respx
from zoneinfo import ZoneInfo

from app.models import AgentRun, utcnow
from app.notify.email import EmailNotifier
from app.notify.feishu import FeishuNotifier
from app.notify.web import WebNotifier
from app.services.scheduler import due_user_ids

TZ = ZoneInfo("Asia/Shanghai")


def _fake_briefing():
    item = SimpleNamespace(
        title="演示新闻",
        source="Demo",
        url="https://example.com/1",
        reason="命中偏好",
        published_at="2026-10-20T08:00:00+00:00",
    )
    return SimpleNamespace(title="AI Daily · 测试", summary="总览", items=[item])


def test_due_user_ids_respects_push_time(database, session, user):
    later = datetime(2026, 10, 20, 7, 0, tzinfo=TZ)  # 08:00 之前 → 不该触发
    assert due_user_ids(database, now=later, tz=TZ) == []

    due_time = datetime(2026, 10, 20, 8, 5, tzinfo=TZ)
    assert due_user_ids(database, now=due_time, tz=TZ) == [user.id]


def test_due_user_ids_skips_when_already_run_today(database, session, user):
    session.add(
        AgentRun(
            user_id=user.id,
            status="success",
            trigger="schedule",
            llm_mode="mock",
            model="mock-model",
            started_at=utcnow(),
        )
    )
    session.commit()
    due_time = datetime.now(TZ) + __import__("datetime").timedelta(hours=1)
    assert due_user_ids(database, now=due_time, tz=TZ) == []


def test_web_notifier_always_succeeds(test_settings):
    result = WebNotifier(test_settings).send(_fake_briefing(), SimpleNamespace(name="用户", email="a@b.com"))
    assert result.status == "success"


def test_feishu_skipped_without_webhook(test_settings):
    result = FeishuNotifier(test_settings).send(_fake_briefing(), SimpleNamespace(name="用户", email="a@b.com"))
    assert result.status == "skipped"


@respx.mock
def test_feishu_success(test_settings):
    settings = test_settings.model_copy(update={"feishu_webhook_url": "https://open.feishu.cn/webhook/test"})
    respx.post("https://open.feishu.cn/webhook/test").mock(return_value=httpx.Response(200, json={"code": 0}))
    result = FeishuNotifier(settings).send(_fake_briefing(), SimpleNamespace(name="用户", email="a@b.com"))
    assert result.status == "success"


@respx.mock
def test_feishu_failure_is_reported(test_settings):
    settings = test_settings.model_copy(update={"feishu_webhook_url": "https://open.feishu.cn/webhook/bad"})
    respx.post("https://open.feishu.cn/webhook/bad").mock(
        return_value=httpx.Response(200, json={"code": 19021, "msg": "sign match fail"})
    )
    result = FeishuNotifier(settings).send(_fake_briefing(), SimpleNamespace(name="用户", email="a@b.com"))
    assert result.status == "failed"
    assert "19021" in result.detail


def test_feishu_network_error_is_caught(test_settings):
    settings = test_settings.model_copy(update={"feishu_webhook_url": "https://open.feishu.cn/webhook/err"})
    with respx.mock:
        respx.post("https://open.feishu.cn/webhook/err").mock(side_effect=httpx.ConnectError("boom"))
        result = FeishuNotifier(settings).send(_fake_briefing(), SimpleNamespace(name="用户", email="a@b.com"))
    assert result.status == "failed"


def test_email_skipped_without_config(test_settings):
    result = EmailNotifier(test_settings).send(_fake_briefing(), SimpleNamespace(name="用户", email="a@b.com"))
    assert result.status == "skipped"


def test_email_skipped_without_user_email(test_settings):
    settings = test_settings.model_copy(update={"smtp_host": "smtp.example.com", "smtp_user": "u", "smtp_password": "p"})
    result = EmailNotifier(settings).send(_fake_briefing(), SimpleNamespace(name="用户", email=None))
    assert result.status == "skipped"


@pytest.mark.parametrize("channels", [["web"], ["web", "feishu"]])
def test_build_notifiers(test_settings, channels):
    from app.notify import build_notifiers

    notifiers = build_notifiers(test_settings, channels)
    assert [notifier.channel for notifier in notifiers] == channels


def test_start_of_day_used_for_dedup():
    from app.services.scheduler import _start_of_day_utc

    start = _start_of_day_utc(datetime(2026, 10, 20, 15, 0, tzinfo=TZ), TZ)
    assert start == datetime(2026, 10, 19, 16, 0, tzinfo=timezone.utc)
