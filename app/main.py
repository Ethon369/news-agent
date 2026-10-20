"""FastAPI 应用入口。

启动顺序（lifespan）：
1. 执行 SQL migration（幂等，fail fast）；
2. 创建 workspace 目录；
3. 构建 AgentRunner；
4. 启动每日调度器（可关闭）；
5. 关闭时优雅停止调度器。
"""

from __future__ import annotations

import logging
from contextlib import asynccontextmanager
from pathlib import Path

from fastapi import FastAPI, Request
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse
from fastapi.staticfiles import StaticFiles

from app import __version__
from app.api import api_router
from app.config import Settings, get_settings
from app.db import Database
from app.schemas import CODE_BAD_REQUEST, CODE_INTERNAL, ApiException, err
from app.services.runner import AgentRunner
from app.services.scheduler import DailyScheduler

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s %(levelname)s [%(name)s] %(message)s",
)
logger = logging.getLogger("ai_daily")

STATIC_DIR = Path(__file__).parent / "static"


def create_app(
    settings: Settings | None = None,
    database: Database | None = None,
    runner: AgentRunner | None = None,
    start_scheduler: bool | None = None,
) -> FastAPI:
    settings = settings or get_settings()
    db = database or Database(settings)
    agent_runner = runner or AgentRunner(settings, db)
    scheduler = DailyScheduler(settings, agent_runner, db)

    @asynccontextmanager
    async def lifespan(app: FastAPI):
        applied = db.migrate()
        if applied:
            logger.info("applied migrations: %s", applied)
        settings.workspace_path.mkdir(parents=True, exist_ok=True)
        app.state.db = db
        app.state.settings = settings
        app.state.runner = agent_runner
        app.state.scheduler = scheduler
        should_start = settings.scheduler_enabled if start_scheduler is None else start_scheduler
        if should_start:
            scheduler.start()
            logger.info("scheduler started (tick %ss)", 300)
        logger.info(
            "AI Daily Agent ready: llm_mode=%s model=%s",
            settings.llm_mode,
            settings.llm_model if settings.llm_mode == "real" else "mock-model",
        )
        try:
            yield
        finally:
            scheduler.shutdown()

    app = FastAPI(title="AI Daily Agent", version=__version__, lifespan=lifespan)

    app.include_router(api_router, prefix="/api")

    @app.exception_handler(ApiException)
    async def handle_api_exception(_request: Request, exc: ApiException) -> JSONResponse:
        return JSONResponse(status_code=exc.http_status, content=err(exc.code, exc.message))

    @app.exception_handler(RequestValidationError)
    async def handle_validation_error(_request: Request, exc: RequestValidationError) -> JSONResponse:
        first = exc.errors()[0] if exc.errors() else {}
        location = ".".join(str(part) for part in first.get("loc", []) if part != "body")
        message = first.get("msg", "参数校验失败")
        return JSONResponse(
            status_code=400,
            content=err(CODE_BAD_REQUEST, f"参数校验失败: {location} {message}".strip()),
        )

    @app.exception_handler(Exception)
    async def handle_unexpected(_request: Request, exc: Exception) -> JSONResponse:
        logger.exception("unhandled error: %s", exc)
        return JSONResponse(status_code=500, content=err(CODE_INTERNAL, "服务器内部错误"))

    if STATIC_DIR.exists():
        app.mount("/", StaticFiles(directory=str(STATIC_DIR), html=True), name="static")

    return app


app = create_app()
