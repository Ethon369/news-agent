"""命令行入口：``python -m app <command>``。

命令：
- serve            启动 Web 服务
- initdb           只执行 migration
- run --user-id N  同步跑一次简报（--mock 强制离线演示）
- demo             一键创建演示用户并跑一次 mock 简报，打印结果
"""

from __future__ import annotations

import argparse
import sys

from app import __version__
from app.config import get_settings
from app.db import Database
from app.models import User
from app.schemas import subscription_to_dict
from app.services.runner import AgentRunner


def _cmd_serve(args: argparse.Namespace) -> int:
    import uvicorn

    settings = get_settings()
    host = args.host or settings.app_host
    port = args.port or settings.app_port
    print(f"AI Daily Agent v{__version__} → http://{host}:{port}")
    uvicorn.run("app.main:app", host=host, port=port, log_level="info")
    return 0


def _cmd_initdb(_args: argparse.Namespace) -> int:
    settings = get_settings()
    db = Database(settings)
    applied = db.migrate()
    print(f"数据库就绪: {settings.database_url}")
    print(f"本次应用 migration: {applied or '（无，已是最新）'}")
    return 0


def _find_user(db: Database, user_id: int | None, email: str | None) -> int:
    session = db.session_factory()
    try:
        if user_id:
            user = session.get(User, user_id)
        elif email:
            user = session.query(User).filter(User.email == email).one_or_none()
        else:
            user = session.query(User).order_by(User.id).first()
        if user is None:
            raise SystemExit("找不到用户，请先通过 Web 页面或 demo 命令创建")
        return user.id
    finally:
        session.close()


def _cmd_run(args: argparse.Namespace) -> int:
    settings = get_settings()
    db = Database(settings)
    db.migrate()
    user_id = _find_user(db, args.user_id, args.email)
    runner = AgentRunner(settings, db)
    print(f"开始为 user={user_id} 生成简报（mock={args.mock}）...")
    run_id = runner.run_for_user(user_id, trigger="cli", mock=args.mock)
    session = db.session_factory()
    try:
        from app.models import AgentRun, Briefing

        run = session.get(AgentRun, run_id)
        print(f"运行 #{run.id} 状态: {run.status}，步数: {run.step_count}，工具调用: {run.tool_call_count}")
        if run.briefing_id:
            briefing = session.get(Briefing, run.briefing_id)
            print("\n" + "=" * 60)
            print(briefing.content_md)
            print("=" * 60)
        if run.error:
            print(f"错误: {run.error}")
        return 0 if run.status == "success" else 1
    finally:
        session.close()


def _cmd_demo(args: argparse.Namespace) -> int:
    from app.models import Subscription, utcnow
    from app.schemas import dump_json_list

    settings = get_settings()
    db = Database(settings)
    db.migrate()
    session = db.session_factory()
    try:
        user = session.query(User).order_by(User.id).first()
        if user is None:
            user = User(name="演示用户", email="demo@example.com", timezone=settings.app_timezone)
            session.add(user)
            session.flush()
        if user.subscription is None:
            session.add(
                Subscription(
                    user_id=user.id,
                    topics=dump_json_list(["AI Agent", "大模型", "开源模型"]),
                    keywords=dump_json_list(["AI", "LLM", "Agent"]),
                    exclude_keywords=dump_json_list([]),
                    max_items=5,
                    language="zh",
                    channels=dump_json_list(["web"]),
                    push_time=settings.daily_run_time,
                    enabled=True,
                    updated_at=utcnow(),
                )
            )
        session.commit()
        session.refresh(user)
        user_id = user.id
        prefs = subscription_to_dict(user.subscription) or {}
    finally:
        session.close()
    print(f"演示用户: id={user_id} 偏好={prefs}")
    runner = AgentRunner(settings, db)
    run_id = runner.run_for_user(user_id, trigger="demo", mock=args.mock)
    session = db.session_factory()
    try:
        from app.models import AgentRun, Briefing

        run = session.get(AgentRun, run_id)
        print(f"运行 #{run.id}: {run.status}（{run.step_count} 步 / {run.tool_call_count} 次工具调用）")
        if run.briefing_id:
            print(session.get(Briefing, run.briefing_id).content_md)
        if run.error:
            print(f"错误: {run.error}")
        return 0 if run.status == "success" else 1
    finally:
        session.close()


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="python -m app", description="AI Daily Agent CLI")
    parser.add_argument("--version", action="version", version=f"ai-daily-agent {__version__}")
    sub = parser.add_subparsers(dest="command", required=True)

    serve = sub.add_parser("serve", help="启动 Web 服务")
    serve.add_argument("--host")
    serve.add_argument("--port", type=int)
    serve.set_defaults(func=_cmd_serve)

    initdb = sub.add_parser("initdb", help="执行数据库 migration")
    initdb.set_defaults(func=_cmd_initdb)

    run = sub.add_parser("run", help="同步运行一次简报")
    run.add_argument("--user-id", type=int)
    run.add_argument("--email")
    run.add_argument("--mock", action="store_true", help="强制使用 mock 模型与离线新闻源")
    run.set_defaults(func=_cmd_run)

    demo = sub.add_parser("demo", help="创建演示用户并跑一次")
    demo.add_argument("--mock", action="store_true", default=True, help="默认走 mock（离线）")
    demo.set_defaults(func=_cmd_demo)
    return parser


def main(argv: list[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)
    return args.func(args)


if __name__ == "__main__":
    sys.exit(main())
