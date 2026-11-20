from collections.abc import MutableMapping
from typing import Any
from uuid import uuid4

from starlette.types import ASGIApp, Receive, Scope, Send

from app.common.i18n import negotiate_locale


class RequestContextMiddleware:
    """Pure ASGI middleware; avoids BaseHTTPMiddleware contextvars limitations."""

    def __init__(self, app: ASGIApp, default_locale: str = "zh-CN") -> None:
        self.app = app
        self.default_locale = default_locale

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        if scope["type"] != "http":
            await self.app(scope, receive, send)
            return
        headers = dict(scope.get("headers", []))
        locale = negotiate_locale(
            headers.get(b"accept-language", b"").decode("latin-1"), self.default_locale
        )
        state = scope.setdefault("state", {})
        request_id = str(uuid4())
        state["request_id"] = request_id
        state["locale"] = locale

        async def send_with_headers(message: MutableMapping[str, Any]) -> None:
            if message["type"] == "http.response.start":
                response_headers = [
                    (key, value)
                    for key, value in message.get("headers", [])
                    if key.lower()
                    not in {
                        b"x-request-id",
                        b"content-language",
                        b"x-content-type-options",
                        b"referrer-policy",
                        b"x-frame-options",
                    }
                ]
                response_headers.extend(
                    [
                        (b"x-request-id", request_id.encode("ascii")),
                        (b"content-language", locale.encode("ascii")),
                        (b"x-content-type-options", b"nosniff"),
                        (b"referrer-policy", b"strict-origin-when-cross-origin"),
                        (b"x-frame-options", b"DENY"),
                    ]
                )
                message["headers"] = response_headers
            await send(message)

        await self.app(scope, receive, send_with_headers)
