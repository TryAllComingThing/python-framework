from fastapi import APIRouter

from app.api.iam_router import router as iam_router
from app.api.iam_router import v2_router as iam_v2_router
from app.core.health import router as health_router
from app.modules.auth.router import router as auth_router
from app.modules.files.router import router as files_router


def build_router() -> APIRouter:
    router = APIRouter()
    router.include_router(health_router)
    router.include_router(auth_router)
    router.include_router(iam_router)
    router.include_router(iam_v2_router)
    router.include_router(files_router)
    return router
