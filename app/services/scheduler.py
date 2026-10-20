"""每日调度：每 5 分钟 tick 一次，找到「推送时间已到且今天还没跑过」的用户。

为什么用 tick 而不是每个用户一个 cron job：
- 用户可能随时改 push_time，tick 方案无需重建 job；
- 进程重启后状态从数据库推导，不会漏跑也不会重复跑；
- 逻辑可以脱离 APScheduler 单测（``run_due_users``）。
"""

from __future__ import annotations

import logging
from datetime import UTC, datetime, time
from zoneinfo import ZoneInfo

from apscheduler.schedulers.background import BackgroundScheduler
from sqlalchemy import select

from app.config import Settings
from app.db import Database
from app.models import AgentRun, Subscription, User

logger = logging.getLogger(__name__)

TICK_SECONDS = 300


def _start_of_day_utc(now: datetime, tz: ZoneInfo) -> datetime:
    local_start = datetime.combine(now.astimezone(tz).date(), time.min, tzinfo=tz)
    return local_start.astimezone(UTC)


def due_user_ids(db: Database, now: datetime | None = None, tz: ZoneInfo | None = None) -> list[int]:
    """返回此刻应当触发的用户 id 列表（push_time <= 当前时刻且今日无定时运行）。"""
    tz = tz or ZoneInfo("Asia/Shanghai")
    now = now or datetime.now(tz)
    local_now = now.astimezone(tz)
    current_hhmm = local_now.strftime("%H:%M")
    day_start = _start_of_day_utc(now, tz)

    session = db.session_factory()
    try:
        rows = session.execute(
            select(User.id, Subscription.push_time)
            .join(Subscription, Subscription.user_id == User.id)
            .where(Subscription.enabled.is_(True))
        ).all()

        due: list[int] = []
        for user_id, push_time in rows:
            if not push_time or current_hhmm < push_time:
                continue
            already = session.execute(
                select(AgentRun.id)
                .where(AgentRun.user_id == user_id)
                .where(AgentRun.trigger == "schedule")
                .where(AgentRun.started_at >= day_start)
                .limit(1)
            ).first()
            if already is None:
                due.append(user_id)
        return due
    finally:
        session.close()


def run_due_users(runner, db: Database, now: datetime | None = None, tz: ZoneInfo | None = None) -> list[int]:
    triggered = []
    for user_id in due_user_ids(db, now=now, tz=tz):
        try:
            run_id = runner.trigger_async(user_id, trigger="schedule")
            triggered.append(user_id)
            logger.info("scheduled briefing triggered: user=%s run=%s", user_id, run_id)
        except Exception:  # noqa: BLE001 - 单个用户失败不影响其他人
            logger.exception("failed to trigger scheduled run for user %s", user_id)
    return triggered


class DailyScheduler:
    """APScheduler 封装：应用生命周期内启动/停止。"""

    def __init__(self, settings: Settings, runner, db: Database) -> None:
        self.settings = settings
        self.runner = runner
        self.db = db
        self._scheduler: BackgroundScheduler | None = None

    def start(self) -> bool:
        if not self.settings.scheduler_enabled:
            return False
        tz = ZoneInfo(self.settings.app_timezone)
        scheduler = BackgroundScheduler(timezone=tz)
        scheduler.add_job(
            self._tick,
            trigger="interval",
            seconds=TICK_SECONDS,
            id="daily-briefing-tick",
            replace_existing=True,
            max_instances=1,
            coalesce=True,
        )
        scheduler.start()
        self._scheduler = scheduler
        return True

    def _tick(self) -> None:
        try:
            run_due_users(self.runner, self.db)
        except Exception:  # noqa: BLE001 - 调度器必须活着
            logger.exception("scheduler tick failed")

    def shutdown(self) -> None:
        if self._scheduler is not None:
            self._scheduler.shutdown(wait=False)
            self._scheduler = None
