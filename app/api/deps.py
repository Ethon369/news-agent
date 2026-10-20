"""API 依赖：数据库会话与运行时对象。"""

from __future__ import annotations

from collections.abc import Iterator

from fastapi import Request
from sqlalchemy.orm import Session

from app.config import Settings
from app.db import Database
from app.services.runner import AgentRunner


def get_settings_dep(request: Request) -> Settings:
    return request.app.state.settings


def get_database(request: Request) -> Database:
    return request.app.state.db


def get_runner(request: Request) -> AgentRunner:
    return request.app.state.runner


def get_session(request: Request) -> Iterator[Session]:
    db: Database = request.app.state.db
    session = db.session_factory()
    try:
        yield session
        session.commit()
    except Exception:
        session.rollback()
        raise
    finally:
        session.close()
