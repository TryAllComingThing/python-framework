"""Cookie-based authentication HTTP adapters; database writes live in services."""

from typing import Annotated

from fastapi import APIRouter, Depends, Request, Response
from sqlalchemy.ext.asyncio import AsyncSession

from app.common.openapi import (
    AUTH_COOKIE_RESPONSE_HEADERS,
    CSRF_HEADER,
    ORIGIN_HEADER,
    error_responses,
)
from app.common.responses import ApiResponse, success
from app.core.codes import ErrorCode
from app.core.database import get_session
from app.core.errors import AppError
from app.modules.auth.dependencies import Identity, csrf_identity, get_identity
from app.modules.auth.schemas import (
    CurrentUserResponse,
    LoginRequest,
    LoginResponse,
    LogoutResponse,
    RotateSessionResponse,
)
from app.modules.auth.security import SESSION_COOKIE_NAME
from app.modules.auth.service import (
    authenticate_and_create_session,
    revoke_session,
    rotate_session_credential,
)

router = APIRouter(prefix="/api/v1/auth", tags=["auth"])
SessionDep = Annotated[AsyncSession, Depends(get_session)]
IdentityDep = Annotated[Identity, Depends(get_identity)]
CsrfIdentityDep = Annotated[Identity, Depends(csrf_identity)]


def _set_session_cookie(request: Request, response: Response, token: str) -> None:
    """Issue a secure, HttpOnly session cookie with one consistent policy."""
    response.set_cookie(
        SESSION_COOKIE_NAME,
        token,
        httponly=True,
        secure=request.app.state.cookie_secure,
        samesite="lax",
        path="/",
        max_age=request.app.state.session_ttl_seconds,
    )
    response.headers["Cache-Control"] = "no-store"


def _delete_session_cookie(request: Request, response: Response) -> None:
    """Expire the session cookie using the same security attributes."""
    response.delete_cookie(
        SESSION_COOKIE_NAME,
        path="/",
        secure=request.app.state.cookie_secure,
        httponly=True,
        samesite="lax",
    )


@router.post(
    "/login",
    response_model=ApiResponse[LoginResponse],
    operation_id="auth_login",
    responses={
        200: {"headers": AUTH_COOKIE_RESPONSE_HEADERS},
        **error_responses(401, 403, 422, 429, 500, 503),
    },
    openapi_extra={"parameters": [ORIGIN_HEADER]},
)
async def login(
    payload: LoginRequest,
    request: Request,
    response: Response,
    db: SessionDep,
) -> ApiResponse[LoginResponse]:
    """Authenticate and issue credentials after verifying the trusted Origin."""
    if not request.app.state.cookie_auth_enabled:
        raise AppError(ErrorCode.FORBIDDEN, 403)
    if request.headers.get("origin", "") not in request.app.state.csrf_origins:
        raise AppError(ErrorCode.FORBIDDEN, 403)
    ip = request.client.host if request.client else "unknown"
    credentials = await authenticate_and_create_session(
        db,
        username=payload.username,
        password=payload.password,
        ip=ip,
        request_id=request.state.request_id,
        session_ttl_seconds=request.app.state.session_ttl_seconds,
    )
    _set_session_cookie(request, response, credentials.session_token)
    return success(
        LoginResponse(
            csrf_token=credentials.csrf_token,
            user_id=credentials.user_id,
        ),
        request.state.request_id,
    )


@router.get(
    "/me",
    response_model=ApiResponse[CurrentUserResponse],
    operation_id="auth_me",
    responses={
        200: {"headers": {"Cache-Control": AUTH_COOKIE_RESPONSE_HEADERS["Cache-Control"]}},
        **error_responses(401, 500, 503),
    },
)
async def me(
    request: Request,
    response: Response,
    identity: IdentityDep,
) -> ApiResponse[CurrentUserResponse]:
    response.headers["Cache-Control"] = "no-store"
    return success(
        CurrentUserResponse(
            id=identity.user.id,
            username=identity.user.username,
            permissions=sorted(identity.principal.permissions),
        ),
        request.state.request_id,
    )


@router.post(
    "/logout",
    response_model=ApiResponse[LogoutResponse],
    operation_id="auth_logout",
    responses={
        200: {"headers": AUTH_COOKIE_RESPONSE_HEADERS},
        **error_responses(401, 403, 500, 503),
    },
    openapi_extra={"parameters": [ORIGIN_HEADER, CSRF_HEADER]},
)
async def logout(
    request: Request,
    response: Response,
    identity: CsrfIdentityDep,
    db: SessionDep,
) -> ApiResponse[LogoutResponse]:
    await revoke_session(
        db,
        session=identity.session,
        actor_id=identity.user.id,
        request_id=request.state.request_id,
    )
    _delete_session_cookie(request, response)
    response.headers["Cache-Control"] = "no-store"
    return success(LogoutResponse(logged_out=True), request.state.request_id)


@router.post(
    "/rotate",
    response_model=ApiResponse[RotateSessionResponse],
    operation_id="auth_rotate_session",
    responses={
        200: {"headers": AUTH_COOKIE_RESPONSE_HEADERS},
        **error_responses(401, 403, 500, 503),
    },
    openapi_extra={"parameters": [ORIGIN_HEADER, CSRF_HEADER]},
)
async def rotate_session(
    request: Request,
    response: Response,
    identity: CsrfIdentityDep,
    db: SessionDep,
) -> ApiResponse[RotateSessionResponse]:
    """Revoke the old session and atomically issue a replacement credential."""
    raw, csrf = await rotate_session_credential(
        db,
        session=identity.session,
        actor_id=identity.user.id,
        auth_version=identity.user.auth_version,
        request_id=request.state.request_id,
    )
    _set_session_cookie(request, response, raw)
    return success(RotateSessionResponse(csrf_token=csrf), request.state.request_id)
