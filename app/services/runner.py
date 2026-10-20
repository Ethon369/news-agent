"""运行编排：加载偏好 → 跑 Agent 循环 → 落库简报 → 推送。

这是「把各层粘起来」的地方，也是后台线程的执行入口。
设计上刻意保持薄：真正的业务规则在 ``briefing.py``，Agent 逻辑在 ``agent/``。

并发与事务约定（AI code review 后加固）：
- 同一用户同一时刻只允许一个运行（进程内按用户加锁，重复触发复用现有 run）；
- 简报与运行状态先提交事务，**推送在事务外进行**，每个渠道单独短事务记 Delivery，
  避免网络等待期间长时间持有 SQLite 写锁、以及「已发出但未落库」的不一致；
- 轨迹落库异常不再被静默吞掉：直接向上抛出，由本层把 run 标记为 failed。
"""

from __future__ import annotations

import logging
import threading
from datetime import date, datetime
from pathlib import Path
from typing import Any
from zoneinfo import ZoneInfo

from sqlalchemy import select, update
from sqlalchemy.orm import Session, selectinload

from app.agent.llm import MockLLM, build_llm
from app.agent.loop import run_agent
from app.agent.registry import ToolRegistry
from app.config import Settings
from app.db import Database
from app.models import AgentRun, AgentStep, Briefing, Delivery, User, utcnow
from app.news.fixture import FixtureNewsService
from app.news.service import NewsService
from app.notify import DeliveryResult, build_notifiers
from app.schemas import subscription_to_dict
from app.services.briefing import (
    history_lines,
    known_urls,
    normalize_items,
    persist_briefing,
    recent_history,
    write_archive,
    write_archive_index,
)
from app.tools import ToolContext, build_default_tools

logger = logging.getLogger(__name__)

DEFAULT_PREFERENCES: dict[str, Any] = {
    "topics": ["AI Agent", "大模型"],
    "keywords": ["AI", "LLM"],
    "exclude_keywords": [],
    "max_items": 5,
    "language": "zh",
    "channels": ["web"],
    "push_time": "08:00",
    "enabled": True,
}


def mark_stale_runs(database: Database) -> int:
    """进程重启后，把遗留的 running 运行标记为失败，避免前端无限轮询/当天不再重试。"""
    session = database.session_factory()
    try:
        result = session.execute(
            update(AgentRun)
            .where(AgentRun.status == "running")
            .values(status="failed", error="服务进程重启，运行被中断", finished_at=utcnow())
        )
        session.commit()
        return int(result.rowcount or 0)
    finally:
        session.close()


class AgentRunner:
    """负责一次简报运行的完整生命周期（可在后台线程中执行）。"""

    def __init__(
        self,
        settings: Settings,
        database: Database,
        llm=None,
        news=None,
    ) -> None:
        self.settings = settings
        self.db = database
        self._llm_override = llm
        self._news_override = news
        self._locks: dict[int, threading.Lock] = {}
        self._locks_guard = threading.Lock()

    # ------------------------------------------------------------------
    # 公共入口
    # ------------------------------------------------------------------
    def trigger_async(self, user_id: int, trigger: str = "manual", mock: bool = False) -> int:
        """创建运行记录并投递到后台线程，立即返回 run_id（供前端轮询）。

        同一用户已有运行中的任务时，直接返回那个 run_id（幂等），不重复启动。
        """
        lock = self._user_lock(user_id)
        if not lock.acquire(blocking=False):
            existing = self._find_running_run(user_id)
            if existing is not None:
                return existing
            raise RuntimeError("该用户已有运行中的简报任务，请稍后再试")

        try:
            mock_mode = mock or self.settings.is_mock_llm
            session = self.db.session_factory()
            try:
                run = AgentRun(
                    user_id=user_id,
                    status="running",
                    trigger=trigger,
                    llm_mode="mock" if mock_mode else "real",
                    model=self._model_name(mock_mode),
                    started_at=utcnow(),
                )
                session.add(run)
                session.commit()
                run_id = run.id
            finally:
                session.close()

            thread = threading.Thread(
                target=self._run_safe,
                args=(run_id, user_id, trigger, mock, lock),
                name=f"agent-run-{run_id}",
                daemon=True,
            )
            thread.start()
            return run_id
        except Exception:
            lock.release()
            raise

    def run_for_user(
        self,
        user_id: int,
        trigger: str = "manual",
        mock: bool = False,
        run_id: int | None = None,
    ) -> int:
        """同步执行一次运行（CLI、测试与后台线程共用）。"""
        session = self.db.session_factory()
        news_service = None
        try:
            user = session.get(User, user_id)
            if user is None:
                raise ValueError(f"用户 {user_id} 不存在")

            preferences = subscription_to_dict(user.subscription) or dict(DEFAULT_PREFERENCES)
            mock_mode = mock or self.settings.is_mock_llm
            run = session.get(AgentRun, run_id) if run_id else None
            if run is None:
                run = AgentRun(
                    user_id=user_id,
                    status="running",
                    trigger=trigger,
                    llm_mode="mock" if mock_mode else "real",
                    model=self._model_name(mock_mode),
                    started_at=utcnow(),
                )
                session.add(run)
                session.commit()
            run.status = "running"
            run.error = ""
            run.llm_mode = "mock" if mock_mode else "real"
            session.commit()
            run_id = run.id

            tz = ZoneInfo(self.settings.app_timezone)
            today = datetime.now(tz).date()
            workspace = self._workspace(user_id)
            for subdir in ("archive", "cache", "drafts"):
                (workspace / subdir).mkdir(parents=True, exist_ok=True)

            llm = self._build_llm(mock_mode, preferences)
            news_service = self._build_news(mock_mode)
            history = recent_history(session, user_id)
            write_archive_index(workspace, history)
            ctx = ToolContext(
                settings=self.settings,
                workspace=workspace,
                user_id=user_id,
                user_name=user.name,
                preferences=preferences,
                run_id=run_id,
                news_service=news_service,
                extra={"history_lines": history_lines(history), "today": today.isoformat()},
            )
            registry = ToolRegistry(build_default_tools(), ctx)
            step_counter = {"value": 0}
            result_steps = {"value": 0}

            def on_event(event) -> None:
                session.add(
                    AgentStep(
                        run_id=run_id,
                        step_index=step_counter["value"],
                        kind=event.kind,
                        thought=(event.thought or "")[:8000],
                        tool_name=event.tool_name or "",
                        tool_args=(event.tool_args or "")[:4000],
                        tool_result=(event.tool_result or "")[:8000],
                        duration_ms=event.duration_ms,
                        created_at=utcnow(),
                    )
                )
                step_counter["value"] += 1
                if event.kind == "tool_call":
                    run.tool_call_count += 1
                if event.kind == "assistant_message":
                    # step_count 语义 = LLM 决策轮次（不是事件数），便于前端展示"第几轮"
                    result_steps["value"] += 1
                    run.step_count = result_steps["value"]
                if event.prompt_tokens:
                    run.prompt_tokens = event.prompt_tokens
                if event.completion_tokens:
                    run.completion_tokens = event.completion_tokens
                session.commit()  # 每步提交，前端轮询才能看到增量轨迹

            result = run_agent(
                ctx,
                llm,
                registry,
                max_steps=self.settings.agent_max_steps,
                token_budget=self.settings.agent_token_budget,
                on_event=on_event,
            )

            run.step_count = max(run.step_count, result.step_count)
            run.tool_call_count = max(run.tool_call_count, result.tool_call_count)
            run.prompt_tokens = max(run.prompt_tokens, result.prompt_tokens)
            run.completion_tokens = max(run.completion_tokens, result.completion_tokens)
            if result.model:
                run.model = result.model

            no_update = False
            briefing_id: int | None = None
            if result.status == "success" and result.briefing_payload:
                briefing, no_update = self._finalize_briefing(
                    session, run, user, preferences, result.briefing_payload, workspace, today
                )
                briefing_id = briefing.id
            else:
                run.status = "failed"
                run.error = result.error or "Agent 未能生成简报"
            run.finished_at = utcnow()
            session.commit()  # 先提交（含简报），再在事务外推送
        except Exception as exc:  # noqa: BLE001 - 后台线程必须记录失败状态
            session.rollback()
            logger.exception("agent run failed: user=%s", user_id)
            self._mark_failed(session, run_id, f"{type(exc).__name__}: {exc}")
            raise
        finally:
            if news_service is not None and hasattr(news_service, "close"):
                try:
                    news_service.close()
                except Exception:  # noqa: BLE001 - 关闭失败不影响结果
                    logger.warning("close news service failed", exc_info=True)
            session.close()

        # 推送在事务外执行，每个渠道独立失败/短事务记账
        if briefing_id is not None:
            self._deliver(
                briefing_id=briefing_id,
                user_id=user_id,
                run_id=run_id,
                channels=preferences.get("channels") or ["web"],
                no_update=no_update,
            )
        return run_id

    # ------------------------------------------------------------------
    # 内部
    # ------------------------------------------------------------------
    def _user_lock(self, user_id: int) -> threading.Lock:
        with self._locks_guard:
            return self._locks.setdefault(user_id, threading.Lock())

    def _find_running_run(self, user_id: int) -> int | None:
        session = self.db.session_factory()
        try:
            row = session.execute(
                select(AgentRun.id)
                .where(AgentRun.user_id == user_id, AgentRun.status == "running")
                .order_by(AgentRun.id.desc())
                .limit(1)
            ).first()
            return int(row[0]) if row else None
        finally:
            session.close()

    def _run_safe(self, run_id: int, user_id: int, trigger: str, mock: bool, lock: threading.Lock) -> None:
        try:
            self.run_for_user(user_id, trigger=trigger, mock=mock, run_id=run_id)
        except Exception:  # noqa: BLE001 - 已在 run_for_user 记录
            logger.exception("background run %s failed", run_id)
        finally:
            lock.release()

    def _finalize_briefing(
        self,
        session: Session,
        run: AgentRun,
        user: User,
        preferences: dict,
        payload: dict,
        workspace: Path,
        today: date,
    ) -> tuple[Briefing, bool]:
        """把模型提交的简报落库；返回 (briefing, 是否「今日无新增」)。"""
        existing_urls = known_urls(session, user.id)
        items, dropped = normalize_items(payload.get("items") or [], preferences, existing_urls)
        if not items:
            title = f"AI Daily · {today.isoformat()}（今日无新增）"
            summary = (
                f"今天筛选出的候选都与历史简报重复或命中排除词，没有需要新增推送的内容。（被过滤 {len(dropped)} 条）"
            )
            briefing = persist_briefing(
                session,
                user=user,
                run_id=run.id,
                title=title,
                summary=summary,
                items=[],
                preferences=preferences,
                briefing_date=today,
                dropped=dropped,
            )
            run.status = "success"
            run.briefing_id = briefing.id
            run.error = "今日无新增内容（去重/排除后为空）"
            session.flush()
            return briefing, True

        title = payload.get("title") or f"AI Daily · {today.isoformat()}"
        briefing = persist_briefing(
            session,
            user=user,
            run_id=run.id,
            title=title,
            summary=payload.get("summary") or "",
            items=items,
            preferences=preferences,
            briefing_date=today,
            dropped=dropped,
        )
        run.status = "success"
        run.briefing_id = briefing.id
        session.flush()
        write_archive(workspace, briefing)
        return briefing, False

    def _deliver(
        self,
        briefing_id: int,
        user_id: int,
        run_id: int,
        channels: list[str],
        no_update: bool,
    ) -> None:
        """事务外推送：加载只读数据 → 逐渠道发送 → 短事务记录 Delivery。"""
        session = self.db.session_factory()
        try:
            briefing = session.get(Briefing, briefing_id)
            user = session.get(User, user_id)
            if briefing is None or user is None:
                return
            _ = list(briefing.items)  # 立即加载，便于随后脱离 session
            session.expunge_all()
        finally:
            session.close()

        server_channels = set(self.settings.enabled_channels) | {"web"}
        for notifier in build_notifiers(self.settings, channels):
            if notifier.channel not in server_channels:
                result = DeliveryResult(
                    channel=notifier.channel,
                    status="skipped",
                    detail="服务端 PUSH_CHANNELS 未启用该通道",
                )
            elif no_update and notifier.channel != "web":
                result = DeliveryResult(
                    channel=notifier.channel,
                    status="skipped",
                    detail="今日无新增内容，不发送外部推送",
                )
            else:
                try:
                    result = notifier.send(briefing, user)
                except Exception as exc:  # noqa: BLE001 - 推送失败不影响简报
                    result = DeliveryResult(channel=notifier.channel, status="failed", detail=str(exc))
            self._record_delivery(run_id, briefing_id, result)

    def _record_delivery(self, run_id: int, briefing_id: int, result: DeliveryResult) -> None:
        session = self.db.session_factory()
        try:
            session.add(
                Delivery(
                    run_id=run_id,
                    briefing_id=briefing_id,
                    channel=result.channel,
                    status=result.status,
                    detail=result.detail[:1000],
                    created_at=utcnow(),
                )
            )
            session.commit()
        except Exception:  # noqa: BLE001 - 记账失败不影响用户已收到的推送
            session.rollback()
            logger.warning("record delivery failed: %s", result.channel, exc_info=True)
        finally:
            session.close()

    def _mark_failed(self, session: Session, run_id: int | None, error: str) -> None:
        if not run_id:
            return
        try:
            session.rollback()
            run = session.get(AgentRun, run_id)
            if run is not None:
                run.status = "failed"
                run.error = error[:2000]
                run.finished_at = utcnow()
                session.commit()
        except Exception:  # noqa: BLE001 - 最后兜底
            session.rollback()

    def _workspace(self, user_id: int) -> Path:
        path = self.settings.workspace_path / f"user_{user_id}"
        path.mkdir(parents=True, exist_ok=True)
        return path

    def _build_llm(self, mock_mode: bool, preferences: dict):
        if self._llm_override is not None:
            return self._llm_override
        if mock_mode:
            return MockLLM(max_items=int(preferences.get("max_items") or 5))
        return build_llm(self.settings)

    def _build_news(self, mock_mode: bool):
        if self._news_override is not None:
            return self._news_override
        if mock_mode:
            return FixtureNewsService()
        return NewsService(self.settings)

    def _model_name(self, mock_mode: bool) -> str:
        return "mock-model" if mock_mode else self.settings.llm_model


__all__ = ["AgentRunner", "DEFAULT_PREFERENCES", "mark_stale_runs"]


def _load_briefing_items(session: Session, briefing_id: int) -> Briefing | None:  # pragma: no cover - 预留
    return session.execute(
        select(Briefing).options(selectinload(Briefing.items)).where(Briefing.id == briefing_id)
    ).scalar_one_or_none()
