"""数据库连接与会话管理 + 轻量 migration 执行器。

设计取舍：
- 用 SQLite 是为了「评审 5 分钟跑通」，但 schema 用纯 SQL migration 管理、
  且 SQLAlchemy 的 DATABASE_URL 可无缝切到 MySQL/Postgres；
- migration 用最朴素的「按文件名顺序执行 + schema_migrations 记账」，
  不引 Alembic：本项目的表结构规模不值得多一层依赖，评审也更容易看懂。
"""

from __future__ import annotations

from collections.abc import Iterator
from datetime import UTC, datetime
from pathlib import Path

from sqlalchemy import create_engine, text
from sqlalchemy.engine import Engine
from sqlalchemy.orm import Session, sessionmaker

from app.config import REPO_ROOT, Settings, get_settings

MIGRATIONS_DIR = REPO_ROOT / "migrations"


def _resolve_sqlite_path(database_url: str) -> str:
    """把 sqlite 相对路径统一解析到仓库根目录，避免受启动目录影响。"""
    prefix = "sqlite:///"
    if not database_url.startswith(prefix):
        return database_url
    raw = database_url[len(prefix) :]
    if raw == ":memory:" or raw.startswith("file:"):
        return database_url
    path = Path(raw)
    if not path.is_absolute():
        path = REPO_ROOT / path
    path.parent.mkdir(parents=True, exist_ok=True)
    return f"{prefix}{path.as_posix()}"


def create_db_engine(settings: Settings | None = None) -> Engine:
    settings = settings or get_settings()
    url = _resolve_sqlite_path(settings.database_url)
    connect_args = {"check_same_thread": False, "timeout": 30} if url.startswith("sqlite") else {}
    engine = create_engine(url, future=True, connect_args=connect_args)
    if url.startswith("sqlite"):
        # WAL + busy_timeout：后台 Agent 线程写轨迹时，API 读请求不会被锁死
        from sqlalchemy import event

        @event.listens_for(engine, "connect")
        def _set_sqlite_pragma(dbapi_connection, _record):  # pragma: no cover - 连接级钩子
            cursor = dbapi_connection.cursor()
            cursor.execute("PRAGMA journal_mode=WAL")
            cursor.execute("PRAGMA busy_timeout=30000")
            cursor.close()

    return engine


def apply_migrations(engine: Engine, migrations_dir: Path = MIGRATIONS_DIR) -> list[str]:
    """按文件名顺序执行未应用过的 *.sql，返回本次应用的版本列表。"""
    applied: list[str] = []
    with engine.begin() as conn:
        conn.execute(
            text("CREATE TABLE IF NOT EXISTS schema_migrations ( version TEXT PRIMARY KEY, applied_at TEXT NOT NULL)")
        )
        done = {row[0] for row in conn.execute(text("SELECT version FROM schema_migrations"))}
        for sql_file in sorted(migrations_dir.glob("*.sql")):
            version = sql_file.stem
            if version in done:
                continue
            statements = [s.strip() for s in sql_file.read_text(encoding="utf-8").split(";") if s.strip()]
            for statement in statements:
                conn.execute(text(statement))
            conn.execute(
                text("INSERT INTO schema_migrations (version, applied_at) VALUES (:v, :t)"),
                {"v": version, "t": datetime.now(UTC).isoformat()},
            )
            applied.append(version)
    return applied


class Database:
    """极简 DB 门面：engine + session factory，便于测试时替换。"""

    def __init__(self, settings: Settings | None = None) -> None:
        self.settings = settings or get_settings()
        self.engine = create_db_engine(self.settings)
        self.session_factory = sessionmaker(bind=self.engine, expire_on_commit=False, class_=Session)

    def migrate(self) -> list[str]:
        return apply_migrations(self.engine)

    def session(self) -> Iterator[Session]:
        session = self.session_factory()
        try:
            yield session
            session.commit()
        except Exception:
            session.rollback()
            raise
        finally:
            session.close()
