"""Bound ASGI request bodies without buffering or blocking filesystem I/O."""

import json
from uuid import uuid4

from starlette.types import ASGIApp, Message, Receive, Scope, Send

from app.common.i18n import negotiate_locale, translate
from app.core.codes import ErrorCode


class ContentLengthLimitMiddleware:
    """Reject oversized requests as chunks arrive, including chunked uploads.

    This does not buffer the request or consume it before downstream handlers.
    Once a response starts, an oversized stream cannot be turned into a 413;
    the middleware terminates the stream and closes the connection instead.
    """

    def __init__(self, app: ASGIApp, max_bytes: int, default_locale: str = "zh-CN") -> None:
        self.app = app
        self.max_bytes = max_bytes
        self.default_locale = default_locale

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        if scope["type"] != "http":
            await self.app(scope, receive, send)
            return
        header_items = scope.get("headers", [])
        declared_lengths = [
            value for key, value in header_items if key.lower() == b"content-length"
        ]
        has_transfer_encoding = any(key.lower() == b"transfer-encoding" for key, _ in header_items)
        if len(declared_lengths) > 1 or (declared_lengths and has_transfer_encoding):
            # Conflicting framing headers are a request-smuggling hazard.
            await self._reject(scope, send, ErrorCode.BAD_REQUEST, 400)
            return
        if declared_lengths:
            declared = declared_lengths[0]
            if not declared.isdigit():
                await self._reject(scope, send, ErrorCode.BAD_REQUEST, 400)
                return
            try:
                length = int(declared)
            except ValueError:
                # Python limits decimal conversion length; treat it as malformed framing.
                await self._reject(scope, send, ErrorCode.BAD_REQUEST, 400)
                return
            if length > self.max_bytes:
                await self._reject(scope, send, ErrorCode.PAYLOAD_TOO_LARGE, 413)
                return

        total = 0
        response_started = False

        async def limited_receive() -> Message:
            nonlocal total
            message = await receive()
            if message["type"] == "http.request":
                total += len(message.get("body", b""))
                if total > self.max_bytes:
                    raise _BodyLimitExceeded()
            return message

        async def guarded_send(message: Message) -> None:
            nonlocal response_started
            if message["type"] == "http.response.start":
                response_started = True
            await send(message)

        try:
            await self.app(scope, limited_receive, guarded_send)
        except _BodyLimitExceeded:
            if not response_started:
                await self._reject(scope, send)
            else:
                # A response already started: do not emit a second status line.
                raise RuntimeError("request body exceeded limit after response started") from None

    async def _reject(
        self,
        scope: Scope,
        send: Send,
        code_value: ErrorCode = ErrorCode.PAYLOAD_TOO_LARGE,
        status: int = 413,
    ) -> None:
        headers = dict(scope.get("headers", []))
        locale = negotiate_locale(
            headers.get(b"accept-language", b"").decode("latin-1"), self.default_locale
        )
        request_id = scope.setdefault("state", {}).get("request_id", str(uuid4()))
        code = str(code_value)
        body = json.dumps(
            {
                "code": code,
                "message": translate(code, locale),
                "request_id": request_id,
                "details": [],
            },
            ensure_ascii=False,
        ).encode()
        await send(
            {
                "type": "http.response.start",
                "status": status,
                "headers": [
                    (b"content-type", b"application/json"),
                    (b"content-language", locale.encode()),
                    (b"cache-control", b"no-store"),
                ],
            }
        )
        await send({"type": "http.response.body", "body": body})


class _BodyLimitExceeded(Exception):
    """Internal control flow for an oversized streaming request."""
