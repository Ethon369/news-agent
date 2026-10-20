"""路由注册。"""

from fastapi import APIRouter

from app.api.routes_briefings import router as briefings_router
from app.api.routes_meta import router as meta_router
from app.api.routes_runs import router as runs_router
from app.api.routes_users import router as users_router

api_router = APIRouter()
api_router.include_router(meta_router)
api_router.include_router(users_router)
api_router.include_router(briefings_router)
api_router.include_router(runs_router)

__all__ = ["api_router"]
