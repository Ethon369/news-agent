"""为演示录屏准备数据：创建演示身份并可选地先跑一次真实简报。

用法：
    # 只创建身份（幂等）
    python scripts/seed_demo.py
    # 创建身份 + 先跑一次真实简报（用于录屏时展示历史）
    python scripts/seed_demo.py --run
"""

from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from app.config import get_settings  # noqa: E402
from app.db import Database  # noqa: E402
from app.models import Subscription, User, utcnow  # noqa: E402
from app.schemas import dump_json_list  # noqa: E402
from app.services.runner import AgentRunner  # noqa: E402

DEMO_EMAIL = "linyue@example.com"
DEMO_NAME = "林悦"


def ensure_demo_user() -> tuple[int, str]:
    settings = get_settings()
    db = Database(settings)
    db.migrate()
    session = db.session_factory()
    try:
        user = session.query(User).filter(User.email == DEMO_EMAIL).one_or_none()
        channels = ["web"]
        if settings.feishu_webhook_url:
            channels.append("feishu")
        if user is None:
            user = User(name=DEMO_NAME, email=DEMO_EMAIL, timezone=settings.app_timezone)
            session.add(user)
            session.flush()
            session.add(
                Subscription(
                    user_id=user.id,
                    topics=dump_json_list(["AI Agent", "大模型", "开源模型"]),
                    keywords=dump_json_list(["MCP", "Agent", "DeepSeek"]),
                    exclude_keywords=dump_json_list(["招聘"]),
                    max_items=5,
                    language="zh",
                    channels=dump_json_list(channels),
                    push_time="08:30",
                    enabled=True,
                    updated_at=utcnow(),
                )
            )
            session.commit()
            print(f"已创建演示身份：{DEMO_NAME} <{DEMO_EMAIL}> id={user.id} channels={channels}")
        else:
            print(f"演示身份已存在：id={user.id}")
        return user.id, channels
    finally:
        session.close()


def run_seed(user_id: int) -> None:
    settings = get_settings()
    db = Database(settings)
    runner = AgentRunner(settings, db)
    print(f"开始为演示身份生成一份历史简报（llm_mode={settings.llm_mode}）...")
    run_id = runner.run_for_user(user_id, trigger="seed", mock=settings.is_mock_llm)
    session = db.session_factory()
    try:
        from app.models import AgentRun, Briefing

        run = session.get(AgentRun, run_id)
        print(f"运行 #{run.id}: {run.status}（{run.step_count} 轮 / {run.tool_call_count} 次工具调用）")
        if run.briefing_id:
            briefing = session.get(Briefing, run.briefing_id)
            print(f"简报 #{briefing.id}：《{briefing.title}》 {briefing.item_count} 条")
        if run.error:
            print(f"错误：{run.error}")
    finally:
        session.close()


if __name__ == "__main__":
    user_id, _ = ensure_demo_user()
    if "--run" in sys.argv:
        run_seed(user_id)
