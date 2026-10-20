"""简报接口：历史列表与详情（含推送记录）。"""

from __future__ import annotations

from fastapi import APIRouter, Depends, Query
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.api.deps import get_session
from app.models import Briefing, Delivery, User
from app.schemas import (
    CODE_NOT_FOUND,
    ApiException,
    briefing_detail_to_dict,
    briefing_summary_to_dict,
    ok,
)

router = APIRouter(tags=["briefings"])


@router.get("/users/{user_id}/briefings")
def list_briefings(
    user_id: int,
    limit: int = Query(default=20, ge=1, le=100),
    offset: int = Query(default=0, ge=0),
    session: Session = Depends(get_session),
) -> dict:
    if session.get(User, user_id) is None:
        raise ApiException(CODE_NOT_FOUND, f"用户 {user_id} 不存在", 404)
    rows = (
        session.execute(
            select(Briefing).where(Briefing.user_id == user_id).order_by(Briefing.id.desc()).offset(offset).limit(limit)
        )
        .scalars()
        .all()
    )
    return ok([briefing_summary_to_dict(briefing) for briefing in rows])


@router.get("/briefings/{briefing_id}")
def get_briefing(briefing_id: int, session: Session = Depends(get_session)) -> dict:
    briefing = session.get(Briefing, briefing_id)
    if briefing is None:
        raise ApiException(CODE_NOT_FOUND, f"简报 {briefing_id} 不存在", 404)
    deliveries = (
        session.execute(select(Delivery).where(Delivery.briefing_id == briefing_id).order_by(Delivery.id))
        .scalars()
        .all()
    )
    return ok(briefing_detail_to_dict(briefing, deliveries))
