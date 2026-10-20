"""运行与轨迹接口：手动触发 + 轮询进度。"""

from __future__ import annotations

from fastapi import APIRouter, Depends, Query
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.api.deps import get_runner, get_session
from app.models import AgentRun, User
from app.schemas import (
    CODE_NOT_FOUND,
    ApiException,
    RunCreate,
    ok,
    run_summary_to_dict,
    run_to_dict,
)
from app.services.runner import AgentRunner

router = APIRouter(tags=["runs"])


@router.post("/users/{user_id}/run")
def trigger_run(
    user_id: int,
    payload: RunCreate | None = None,
    session: Session = Depends(get_session),
    runner: AgentRunner = Depends(get_runner),
) -> dict:
    if session.get(User, user_id) is None:
        raise ApiException(CODE_NOT_FOUND, f"用户 {user_id} 不存在", 404)
    mock = bool(payload.mock) if payload else False
    run_id = runner.trigger_async(user_id, trigger="manual", mock=mock)
    return ok({"run_id": run_id, "status": "running"})


@router.get("/runs/{run_id}")
def get_run(run_id: int, session: Session = Depends(get_session)) -> dict:
    run = session.get(AgentRun, run_id)
    if run is None:
        raise ApiException(CODE_NOT_FOUND, f"运行 {run_id} 不存在", 404)
    return ok(run_to_dict(run, include_steps=True))


@router.get("/runs")
def list_runs(
    user_id: int | None = Query(default=None),
    limit: int = Query(default=10, ge=1, le=50),
    session: Session = Depends(get_session),
) -> dict:
    statement = select(AgentRun).order_by(AgentRun.id.desc()).limit(limit)
    if user_id is not None:
        statement = select(AgentRun).where(AgentRun.user_id == user_id).order_by(AgentRun.id.desc()).limit(limit)
    rows = session.execute(statement).scalars().all()
    return ok([run_summary_to_dict(run) for run in rows])
