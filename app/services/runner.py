"""运行编排：加载偏好 → 跑 Agent 循环 → 落库简报 → 推送。

这是「把各层粘起来」的地方，也是后台线程的执行入口。
设计上刻意保持薄：真正的业务规则在 ``briefing.py``，Agent 逻辑在 ``agent/``。
"""

from __future__ import annotations

import contextlib
import logging
import threading
from datetime import date
from pathlib import Path
from typing import Any

from sqlalchemy.orm import Session

from app.agent.llm import MockLLM, build_llm
from app.agent.loop import run_agent
from app.agent.registry import ToolRegistry
from app.config import Settings
from app.db import Database
from app.models import AgentRun, AgentStep, Delivery, User, utcnow
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

    # ------------------------------------------------------------------
    # 公共入口
    # ------------------------------------------------------------------
    def trigger_async(self, user_id: int, trigger: str = "manual", mock: bool = False) -> int:
        """创建运行记录并投递到后台线程，立即返回 run_id（供前端轮询）。"""
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
            args=(run_id, user_id, trigger, mock),
            name=f"agent-run-{run_id}",
            daemon=True,
        )
        thread.start()
        return run_id

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
                extra={"history_lines": history_lines(history)},
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
                session.commit()  # 每步提交，前端轮询才能看到增量轨迹

            result = run_agent(
                ctx,
                llm,
                registry,
                max_steps=self.settings.agent_max_steps,
                on_event=on_event,
            )

            run.step_count = max(run.step_count, result.step_count)
            run.tool_call_count = max(run.tool_call_count, result.tool_call_count)
            run.prompt_tokens += result.prompt_tokens
            run.completion_tokens += result.completion_tokens
            if result.model:
                run.model = result.model

            if result.status == "success" and result.briefing_payload:
                self._finalize_success(session, run, user, preferences, result.briefing_payload, workspace)
            else:
                run.status = "failed"
                run.error = result.error or "Agent 未能生成简报"
            run.finished_at = utcnow()
            session.commit()
            return run_id
        except Exception as exc:  # noqa: BLE001 - 后台线程必须吞掉异常并记录
            session.rollback()
            logger.exception("agent run failed: user=%s", user_id)
            self._mark_failed(session, run_id, f"{type(exc).__name__}: {exc}")
            raise
        finally:
            if news_service is not None and hasattr(news_service, "close"):
                with contextlib.suppress(Exception):
                    news_service.close()
            session.close()

    # ------------------------------------------------------------------
    # 内部
    # ------------------------------------------------------------------
    def _run_safe(self, run_id: int, user_id: int, trigger: str, mock: bool) -> None:
        try:
            self.run_for_user(user_id, trigger=trigger, mock=mock, run_id=run_id)
        except Exception:  # noqa: BLE001 - 已在 run_for_user 记录
            logger.exception("background run %s failed", run_id)

    def _finalize_success(
        self,
        session: Session,
        run: AgentRun,
        user: User,
        preferences: dict,
        payload: dict,
        workspace: Path,
    ) -> None:
        existing_urls = known_urls(session, user.id)
        items, dropped = normalize_items(payload.get("items") or [], preferences, existing_urls)
        today = date.today().isoformat()
        if not items:
            # 全部被去重/排除：这不是失败，而是「今日无新增」——落一份空简报并说明原因
            title = f"AI Daily · {today}（今日无新增）"
            summary = (
                f"今天筛选出的候选都与历史简报重复或命中排除词，没有需要新增推送的内容。"
                f"（被过滤 {len(dropped)} 条）"
            )
            briefing = persist_briefing(
                session,
                user=user,
                run_id=run.id,
                title=title,
                summary=summary,
                items=[],
                preferences=preferences,
                dropped=dropped,
            )
            run.status = "success"
            run.briefing_id = briefing.id
            run.error = "今日无新增内容（去重/排除后为空）"
            session.flush()
            for notifier in build_notifiers(self.settings, preferences.get("channels") or ["web"]):
                if notifier.channel != "web":
                    session.add(
                        Delivery(
                            run_id=run.id,
                            briefing_id=briefing.id,
                            channel=notifier.channel,
                            status="skipped",
                            detail="今日无新增内容，不发送外部推送",
                            created_at=utcnow(),
                        )
                    )
            return

        title = payload.get("title") or f"AI Daily · {today}"
        briefing = persist_briefing(
            session,
            user=user,
            run_id=run.id,
            title=title,
            summary=payload.get("summary") or "",
            items=items,
            preferences=preferences,
            dropped=dropped,
        )
        run.status = "success"
        run.briefing_id = briefing.id
        session.flush()
        write_archive(workspace, briefing)

        server_channels = set(self.settings.enabled_channels) | {"web"}
        for notifier in build_notifiers(self.settings, preferences.get("channels") or ["web"]):
            if notifier.channel not in server_channels:
                result = DeliveryResult(
                    channel=notifier.channel, status="skipped", detail="服务端 PUSH_CHANNELS 未启用该通道"
                )
            else:
                try:
                    result = notifier.send(briefing, user)
                except Exception as exc:  # noqa: BLE001 - 推送失败不影响简报
                    result = DeliveryResult(channel=notifier.channel, status="failed", detail=str(exc))
            session.add(
                Delivery(
                    run_id=run.id,
                    briefing_id=briefing.id,
                    channel=result.channel,
                    status=result.status,
                    detail=result.detail[:1000],
                    created_at=utcnow(),
                )
            )

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
