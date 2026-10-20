"""调度器与运行一致性测试：push_time 判定、时段去重、进程重启清理、并发触发保护。"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from zoneinfo import ZoneInfo

from app.models import AgentRun, utcnow
from app.services.runner import mark_stale_runs
from app.services.scheduler import _start_of_day_utc, due_user_ids

TZ = ZoneInfo("Asia/Shanghai")


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
    due_time = datetime.now(TZ) + timedelta(hours=1)
    assert due_user_ids(database, now=due_time, tz=TZ) == []


def test_due_user_ids_skips_manual_run_today(database, session, user):
    """今天已经手动跑过，定时任务不应再重复触发。"""
    session.add(
        AgentRun(
            user_id=user.id,
            status="success",
            trigger="manual",
            llm_mode="mock",
            model="mock-model",
            started_at=utcnow(),
        )
    )
    session.commit()
    due_time = datetime.now(TZ) + timedelta(hours=1)
    assert due_user_ids(database, now=due_time, tz=TZ) == []


def test_start_of_day_used_for_dedup():
    start = _start_of_day_utc(datetime(2026, 10, 20, 15, 0, tzinfo=TZ), TZ)
    assert start == datetime(2026, 10, 19, 16, 0, tzinfo=UTC)


def test_stale_running_runs_are_marked_failed(database, user):
    session = database.session_factory()
    try:
        session.add(
            AgentRun(user_id=user.id, status="running", trigger="manual", llm_mode="mock", model="mock-model")
        )
        session.commit()
    finally:
        session.close()

    assert mark_stale_runs(database) == 1

    session = database.session_factory()
    try:
        run = session.query(AgentRun).order_by(AgentRun.id.desc()).first()
        assert run.status == "failed"
        assert "重启" in run.error
    finally:
        session.close()


def test_concurrent_trigger_guard(test_settings, database, user):
    """同一用户已有运行中的任务时，不重复启动（返回/拒绝而不是双开）。"""
    from app.services.runner import AgentRunner

    runner = AgentRunner(test_settings, database)
    lock = runner._user_lock(user.id)
    lock.acquire()
    try:
        try:
            runner.trigger_async(user.id)
        except RuntimeError as exc:
            assert "运行中" in str(exc)
        else:  # pragma: no cover - 若走到了这里说明 guard 失效
            raise AssertionError("并发触发没有被拦截")
    finally:
        lock.release()
