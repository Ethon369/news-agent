"""用户与订阅接口。"""

from __future__ import annotations

from fastapi import APIRouter, Depends
from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.api.deps import get_session, get_settings_dep
from app.config import Settings
from app.models import Subscription, User, utcnow
from app.schemas import (
    CODE_CONFLICT,
    CODE_NOT_FOUND,
    ApiException,
    SubscriptionUpdate,
    UserCreate,
    dump_json_list,
    ok,
    subscription_to_dict,
    user_to_dict,
)

router = APIRouter(prefix="/users", tags=["users"])

DEFAULT_TOPICS = ["AI Agent", "大模型"]
DEFAULT_KEYWORDS = ["AI", "LLM"]


def _default_subscription(settings: Settings, user_id: int) -> Subscription:
    return Subscription(
        user_id=user_id,
        topics=dump_json_list(DEFAULT_TOPICS),
        keywords=dump_json_list(DEFAULT_KEYWORDS),
        exclude_keywords=dump_json_list([]),
        max_items=5,
        language="zh",
        channels=dump_json_list(["web"]),
        push_time=settings.daily_run_time,
        enabled=True,
        updated_at=utcnow(),
    )


@router.get("")
def list_users(session: Session = Depends(get_session)) -> dict:
    users = session.execute(select(User).order_by(User.created_at.desc())).scalars().all()
    return ok([user_to_dict(user) for user in users])


@router.post("")
def create_user(
    payload: UserCreate,
    session: Session = Depends(get_session),
    settings: Settings = Depends(get_settings_dep),
) -> dict:
    if payload.email:
        existing = session.execute(select(User).where(User.email == payload.email)).scalar_one_or_none()
        if existing is not None:
            raise ApiException(CODE_CONFLICT, f"邮箱 {payload.email} 已存在，直接选择该用户即可", 409)
    user = User(
        name=payload.name,
        email=payload.email,
        timezone=payload.timezone,
        created_at=utcnow(),
    )
    session.add(user)
    try:
        session.flush()
        session.add(_default_subscription(settings, user.id))
        session.commit()
    except IntegrityError:
        # 并发下 check-then-insert 会撞唯一约束：统一映射为 409，而不是 500
        session.rollback()
        raise ApiException(CODE_CONFLICT, f"邮箱 {payload.email} 已存在，直接选择该用户即可", 409) from None
    session.refresh(user)
    return ok(user_to_dict(user))


@router.get("/{user_id}")
def get_user(user_id: int, session: Session = Depends(get_session)) -> dict:
    user = session.get(User, user_id)
    if user is None:
        raise ApiException(CODE_NOT_FOUND, f"用户 {user_id} 不存在", 404)
    return ok(user_to_dict(user))


@router.put("/{user_id}/subscription")
def update_subscription(
    user_id: int,
    payload: SubscriptionUpdate,
    session: Session = Depends(get_session),
    settings: Settings = Depends(get_settings_dep),
) -> dict:
    user = session.get(User, user_id)
    if user is None:
        raise ApiException(CODE_NOT_FOUND, f"用户 {user_id} 不存在", 404)

    subscription = user.subscription
    if subscription is None:
        subscription = _default_subscription(settings, user.id)
        session.add(subscription)

    data = payload.model_dump(exclude_unset=True)
    if "topics" in data:
        subscription.topics = dump_json_list(data["topics"] or [])
    if "keywords" in data:
        subscription.keywords = dump_json_list(data["keywords"] or [])
    if "exclude_keywords" in data:
        subscription.exclude_keywords = dump_json_list(data["exclude_keywords"] or [])
    if "max_items" in data and data["max_items"] is not None:
        subscription.max_items = int(data["max_items"])
    if "language" in data and data["language"]:
        subscription.language = data["language"]
    if "channels" in data and data["channels"] is not None:
        subscription.channels = dump_json_list(data["channels"])
    if "push_time" in data and data["push_time"]:
        subscription.push_time = data["push_time"]
    if "enabled" in data and data["enabled"] is not None:
        subscription.enabled = bool(data["enabled"])
    subscription.updated_at = utcnow()
    session.commit()
    session.refresh(subscription)
    return ok(subscription_to_dict(subscription))
