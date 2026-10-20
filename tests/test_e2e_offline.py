"""端到端（离线）：一次完整运行从 Agent 循环 → 落库 → 归档 → 推送记录。"""

from __future__ import annotations

from app.models import AgentRun, Briefing, Delivery
from app.services.runner import AgentRunner


def test_offline_end_to_end_run(database, user, test_settings):
    runner = AgentRunner(test_settings, database)
    run_id = runner.run_for_user(user.id, trigger="test", mock=True)

    session = database.session_factory()
    try:
        run = session.get(AgentRun, run_id)
        assert run is not None and run.status == "success"
        assert run.briefing_id is not None
        assert run.step_count >= 9
        assert run.tool_call_count >= 8

        briefing = session.get(Briefing, run.briefing_id)
        assert briefing.item_count >= 1
        assert "https://example.com/ai-daily-demo/" in briefing.content_md

        steps = sorted(run.steps, key=lambda step: step.step_index)
        assert steps
        assert all(step.kind in {"assistant_message", "tool_call", "final", "error"} for step in steps)

        deliveries = session.query(Delivery).filter(Delivery.briefing_id == briefing.id).all()
        assert any(d.channel == "web" and d.status == "success" for d in deliveries)

        # 归档文件与索引供下一轮 read_file/search_content 使用
        archive_file = test_settings.workspace_path / f"user_{user.id}" / "archive" / f"{briefing.briefing_date}.md"
        assert archive_file.exists()
        index_file = archive_file.parent / "index.md"
        assert index_file.exists()
        assert "历史简报索引" in index_file.read_text(encoding="utf-8")
    finally:
        session.close()


def test_second_offline_run_reports_no_update(database, user, test_settings):
    runner = AgentRunner(test_settings, database)
    runner.run_for_user(user.id, trigger="test", mock=True)
    second_run_id = runner.run_for_user(user.id, trigger="test", mock=True)

    session = database.session_factory()
    try:
        run = session.get(AgentRun, second_run_id)
        assert run.status == "success"
        briefing = session.get(Briefing, run.briefing_id)
        assert "无新增" in briefing.title
        assert briefing.item_count == 0
    finally:
        session.close()


def test_failed_run_is_recorded(database, user, test_settings):
    """当 LLM 不可用时，运行失败要落库而不是静默消失。"""

    class BrokenLLM:
        model = "broken"

        def chat(self, *args, **kwargs):
            from app.agent.llm import LLMError

            raise LLMError("模拟模型不可用")

    runner = AgentRunner(test_settings, database, llm=BrokenLLM())
    run_id = runner.run_for_user(user.id, trigger="test", mock=True)

    session = database.session_factory()
    try:
        run = session.get(AgentRun, run_id)
        assert run.status == "failed"
        assert "模拟模型不可用" in run.error
        assert run.finished_at is not None
    finally:
        session.close()
