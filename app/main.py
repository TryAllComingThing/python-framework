from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from pathlib import Path
from typing import Any, cast

from fastapi import FastAPI
from fastapi.exceptions import RequestValidationError
from fastapi.middleware.cors import CORSMiddleware
from starlette.exceptions import HTTPException
from starlette.middleware.trustedhost import TrustedHostMiddleware

from app.api.router import build_router
from app.core.config import Settings, get_settings
from app.core.database import close_database, initialize_database
from app.core.errors import (
    AppError,
    app_error_handler,
    http_error_handler,
    unhandled_error_handler,
    validation_error_handler,
)
from app.core.middleware.context import RequestContextMiddleware
from app.core.middleware.limits import ContentLengthLimitMiddleware
from app.infrastructure.logging import configure_logging
from app.infrastructure.storage import LocalStorage


def create_app(settings: Settings | None = None) -> FastAPI:
    config = settings or get_settings()
    if config.app_env == "production" and config.cookie_auth_enabled and not config.cors_origins:
        raise RuntimeError("Explicit CORS origins required for cookie auth in production")
    if config.cookie_auth_enabled:
        missing_csrf_origins = set(config.csrf_origins) - set(config.cors_origins)
        if missing_csrf_origins:
            missing = ", ".join(sorted(missing_csrf_origins))
            raise RuntimeError(f"CSRF origins must be a subset of CORS origins: {missing}")
        if not config.csrf_origins:
            raise RuntimeError("CSRF origins required when cookie auth is enabled")
    if config.app_env == "production" and not config.trusted_hosts:
        raise RuntimeError("Trusted hosts required in production")
    if config.app_env == "production" and not config.file_malware_scan_enabled:
        raise RuntimeError("Malware scanning is mandatory for production file uploads")

    storage = LocalStorage(Path(config.file_storage_root), max_bytes=config.file_max_bytes)

    @asynccontextmanager
    async def lifespan(app: FastAPI) -> AsyncIterator[None]:
        configure_logging(config.log_level)
        storage.initialize()
        await initialize_database(app, config.database_url)
        try:
            yield
        finally:
            await close_database(app)

    app = FastAPI(title="Python Framework", version="3.4.0", lifespan=lifespan)
    app.add_exception_handler(AppError, cast(Any, app_error_handler))
    app.add_exception_handler(HTTPException, cast(Any, http_error_handler))
    app.add_exception_handler(RequestValidationError, cast(Any, validation_error_handler))
    app.add_exception_handler(Exception, unhandled_error_handler)
    if config.cors_origins:
        app.add_middleware(
            CORSMiddleware,
            allow_origins=config.cors_origins,
            allow_credentials=config.cookie_auth_enabled,
            allow_methods=["GET", "POST", "PUT", "PATCH", "DELETE"],
            allow_headers=[
                "Content-Type",
                "X-CSRF-Token",
                "If-Match",
                "If-None-Match",
                "If-Range",
                "Idempotency-Key",
                "Range",
            ],
            expose_headers=[
                "X-Request-ID",
                "ETag",
                "Accept-Ranges",
                "Content-Length",
                "Content-Range",
                "Content-Disposition",
                "Retry-After",
                "Deprecation",
                "Link",
                "Warning",
            ],
        )
    if config.trusted_hosts:
        app.add_middleware(TrustedHostMiddleware, allowed_hosts=config.trusted_hosts)
    app.add_middleware(
        ContentLengthLimitMiddleware,
        max_bytes=config.max_request_bytes,
        default_locale=config.default_locale,
    )
    app.add_middleware(RequestContextMiddleware, default_locale=config.default_locale)
    app.state.file_storage = storage
    app.state.file_max_bytes = config.file_max_bytes
    app.state.file_malware_scan_enabled = config.file_malware_scan_enabled
    app.state.file_clamd_socket = config.file_clamd_socket
    app.state.csrf_origins = config.csrf_origins
    app.state.cookie_auth_enabled = config.cookie_auth_enabled
    app.state.cookie_secure = config.app_env != "local" and config.app_env != "test"
    app.state.session_ttl_seconds = config.session_ttl_hours * 60 * 60
    app.include_router(build_router())
    return app


app = create_app()
