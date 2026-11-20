import logging
from collections.abc import Mapping

from fastapi import Request
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse
from starlette.exceptions import HTTPException

from app.common.i18n import translate
from app.core.codes import ErrorCode

log = logging.getLogger(__name__)


ERROR_HTTP_STATUS: dict[str, int] = {
    str(ErrorCode.VALIDATION_ERROR): 422,
    str(ErrorCode.BAD_REQUEST): 400,
    str(ErrorCode.METHOD_NOT_ALLOWED): 405,
    str(ErrorCode.NOT_ACCEPTABLE): 406,
    str(ErrorCode.NOT_FOUND): 404,
    str(ErrorCode.CONFLICT): 409,
    str(ErrorCode.PRECONDITION_FAILED): 412,
    str(ErrorCode.PRECONDITION_REQUIRED): 428,
    str(ErrorCode.RANGE_NOT_SATISFIABLE): 416,
    str(ErrorCode.TOO_MANY_REQUESTS): 429,
    str(ErrorCode.PAYLOAD_TOO_LARGE): 413,
    str(ErrorCode.UNSUPPORTED_MEDIA_TYPE): 415,
    str(ErrorCode.INTERNAL_ERROR): 500,
    str(ErrorCode.UNAUTHORIZED): 401,
    str(ErrorCode.FORBIDDEN): 403,
    str(ErrorCode.DATABASE_UNAVAILABLE): 503,
    str(ErrorCode.SERVICE_UNAVAILABLE): 503,
}


class AppError(Exception):
    def __init__(
        self,
        code: ErrorCode | str,
        status_code: int = 400,
        details: list[dict[str, str]] | None = None,
        headers: Mapping[str, str] | None = None,
    ) -> None:
        if str(code) in ERROR_HTTP_STATUS and ERROR_HTTP_STATUS[str(code)] != status_code:
            raise ValueError(f"Error code/status mismatch: {code} / {status_code}")
        self.code = str(code)
        self.status_code = status_code
        self.details = details or []
        self.headers = dict(headers or {})


def _default_error_headers(status: int) -> dict[str, str]:
    """Provide protocol-level metadata required by common HTTP error statuses."""
    if status == 401:
        return {"WWW-Authenticate": 'Session realm="python-framework"'}
    if status == 429:
        return {"Retry-After": "60"}
    return {}


def error_response(
    request: Request,
    code: str,
    status: int,
    details: list[dict[str, str]] | None = None,
    headers: Mapping[str, str] | None = None,
) -> JSONResponse:
    locale = getattr(request.state, "locale", "zh-CN")
    response_headers = {
        "Content-Language": locale,
        **_default_error_headers(status),
        **(headers or {}),
    }
    return JSONResponse(
        status_code=status,
        content={
            "code": code,
            "message": translate(code, locale),
            "request_id": getattr(request.state, "request_id", "unknown"),
            "details": details or [],
        },
        headers=response_headers,
    )


async def app_error_handler(request: Request, exc: AppError) -> JSONResponse:
    return error_response(
        request,
        exc.code,
        exc.status_code,
        exc.details,
        headers=exc.headers,
    )


async def http_error_handler(request: Request, exc: HTTPException) -> JSONResponse:
    codes = {
        400: ErrorCode.BAD_REQUEST,
        401: ErrorCode.UNAUTHORIZED,
        403: ErrorCode.FORBIDDEN,
        404: ErrorCode.NOT_FOUND,
        405: ErrorCode.METHOD_NOT_ALLOWED,
        406: ErrorCode.NOT_ACCEPTABLE,
        409: ErrorCode.CONFLICT,
        412: ErrorCode.PRECONDITION_FAILED,
        416: ErrorCode.RANGE_NOT_SATISFIABLE,
        413: ErrorCode.PAYLOAD_TOO_LARGE,
        415: ErrorCode.UNSUPPORTED_MEDIA_TYPE,
        422: ErrorCode.VALIDATION_ERROR,
        428: ErrorCode.PRECONDITION_REQUIRED,
        429: ErrorCode.TOO_MANY_REQUESTS,
        503: ErrorCode.SERVICE_UNAVAILABLE,
    }
    code = codes.get(
        exc.status_code,
        ErrorCode.INTERNAL_ERROR if exc.status_code >= 500 else ErrorCode.BAD_REQUEST,
    )
    return error_response(
        request,
        str(code),
        exc.status_code,
        headers=exc.headers,
    )


async def validation_error_handler(request: Request, exc: RequestValidationError) -> JSONResponse:
    details = [
        {"field": ".".join(map(str, item["loc"])), "reason": str(item["type"])}
        for item in exc.errors()
    ]
    return error_response(request, str(ErrorCode.VALIDATION_ERROR), 422, details)


async def unhandled_error_handler(request: Request, exc: Exception) -> JSONResponse:
    log.error(
        "Unhandled request error",
        extra={"request_id": getattr(request.state, "request_id", "unknown")},
        exc_info=exc,
    )
    return error_response(request, str(ErrorCode.INTERNAL_ERROR), 500)
