from __future__ import annotations

import json
from typing import Any

import pytest

from app.core.middleware.context import RequestContextMiddleware
from app.core.middleware.limits import ContentLengthLimitMiddleware


@pytest.mark.asyncio
async def test_chunked_body_limit_is_detected_without_buffering() -> None:
    async def downstream(scope: object, receive: object, send: object) -> None:
        while True:
            message = await receive()  # type: ignore[operator]
            if not message.get("more_body", False):
                break
        await send({"type": "http.response.start", "status": 204, "headers": []})  # type: ignore[operator]
        await send({"type": "http.response.body", "body": b""})  # type: ignore[operator]

    messages = iter(
        [
            {"type": "http.request", "body": b"123", "more_body": True},
            {"type": "http.request", "body": b"456", "more_body": False},
        ]
    )
    sent: list[dict[str, Any]] = []

    async def receive() -> dict[str, object]:
        return next(messages)

    async def send(message: dict[str, object]) -> None:
        sent.append(message)

    middleware = ContentLengthLimitMiddleware(downstream, max_bytes=5)  # type: ignore[arg-type]
    scope = {"type": "http", "method": "POST", "headers": [], "state": {}}
    await middleware(scope, receive, send)  # type: ignore[arg-type]

    assert sent[0]["status"] == 413
    body_payload = sent[1]["body"]
    assert isinstance(body_payload, (str, bytes, bytearray))
    body = json.loads(body_payload)
    assert body["code"] == "COMMON.PAYLOAD_TOO_LARGE"


@pytest.mark.parametrize(
    "headers",
    [
        [(b"content-length", b"invalid")],
        [(b"content-length", b"-1")],
        [(b"content-length", b"+1")],
        [(b"content-length", b"9" * 5000)],
        [(b"content-length", b"1"), (b"content-length", b"2")],
        [(b"content-length", b"1"), (b"transfer-encoding", b"chunked")],
    ],
)
async def test_invalid_request_framing_headers_are_rejected(
    headers: list[tuple[bytes, bytes]],
) -> None:
    async def downstream(scope: object, receive: object, send: object) -> None:
        raise AssertionError("invalid framing must be rejected before downstream")

    sent: list[dict[str, Any]] = []

    async def receive() -> dict[str, object]:
        return {"type": "http.request", "body": b"", "more_body": False}

    async def send(message: dict[str, object]) -> None:
        sent.append(message)

    middleware = ContentLengthLimitMiddleware(downstream, max_bytes=5)  # type: ignore[arg-type]
    scope = {"type": "http", "method": "POST", "headers": headers, "state": {}}
    await middleware(scope, receive, send)  # type: ignore[arg-type]

    assert sent[0]["status"] == 400
    body = json.loads(sent[1]["body"])
    assert body["code"] == "COMMON.BAD_REQUEST"


@pytest.mark.asyncio
async def test_request_context_adds_trace_and_security_headers() -> None:
    async def downstream(scope: object, receive: object, send: object) -> None:
        await send({"type": "http.response.start", "status": 200, "headers": []})  # type: ignore[operator]
        await send({"type": "http.response.body", "body": b"ok"})  # type: ignore[operator]

    sent: list[dict[str, Any]] = []

    async def receive() -> dict[str, object]:
        return {"type": "http.request", "body": b"", "more_body": False}

    async def send(message: dict[str, object]) -> None:
        sent.append(message)

    scope = {
        "type": "http",
        "method": "GET",
        "headers": [(b"accept-language", b"en-US")],
        "state": {},
    }
    middleware = RequestContextMiddleware(downstream, default_locale="zh-CN")  # type: ignore[arg-type]
    await middleware(scope, receive, send)  # type: ignore[arg-type]

    header_items = sent[0]["headers"]
    assert isinstance(header_items, list)
    headers = dict(header_items)
    assert headers[b"content-language"] == b"en-US"
    assert len(headers[b"x-request-id"]) > 0
    assert headers[b"x-content-type-options"] == b"nosniff"
