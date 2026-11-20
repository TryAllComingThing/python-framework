"""Authorized upload, download and delete endpoints."""

from __future__ import annotations

import re
import threading
from collections.abc import AsyncIterator, Generator
from typing import Annotated, Protocol
from urllib.parse import quote

from fastapi import APIRouter, Depends, File, Request, UploadFile
from fastapi.responses import Response, StreamingResponse
from sqlalchemy.ext.asyncio import AsyncSession
from starlette.concurrency import iterate_in_threadpool, run_in_threadpool

from app.common.openapi import (
    CSRF_HEADER,
    DOWNLOAD_RESPONSE_HEADERS,
    IF_NONE_MATCH_HEADER,
    IF_RANGE_HEADER,
    ORIGIN_HEADER,
    RANGE_HEADER,
    RANGE_RESPONSE_HEADERS,
    error_responses,
)
from app.common.pagination import Page, PageParams
from app.common.responses import ApiResponse, success
from app.core.codes import ErrorCode
from app.core.database import get_session
from app.core.errors import AppError, error_response
from app.infrastructure.storage import StoragePort
from app.modules.auth.dependencies import Identity, csrf_identity, get_identity
from app.modules.files.query import page_file_metadata, to_file_metadata
from app.modules.files.schemas import FileDeleteResponse, FileMetadataResponse, FileUploadResponse
from app.modules.files.service import (
    authorized_record,
    delete_file,
    record_download,
    upload_file,
)

router = APIRouter(prefix="/api/v1/files", tags=["files"])
SessionDep = Annotated[AsyncSession, Depends(get_session)]
IdentityDep = Annotated[Identity, Depends(get_identity)]
CsrfIdentityDep = Annotated[Identity, Depends(csrf_identity)]
PageDep = Annotated[PageParams, Depends()]
UploadDep = Annotated[UploadFile, File()]
_RANGE_PATTERN = re.compile(r"bytes=(\d*)-(\d*)")


def storage_from_request(request: Request) -> StoragePort:
    """Resolve the private storage adapter attached to this application."""
    return request.app.state.file_storage


def _content_headers(record_name: str, etag: str) -> dict[str, str]:
    return {
        "Content-Disposition": "attachment; filename*=UTF-8''" + quote(record_name),
        "Cache-Control": "private, no-cache",
        "Vary": "Cookie",
        "X-Content-Type-Options": "nosniff",
        "ETag": etag,
        "Accept-Ranges": "bytes",
    }


def _parse_range(value: str, size: int) -> tuple[int, int]:
    """Parse one RFC 7233 byte range and return inclusive start/end offsets."""
    match = _RANGE_PATTERN.fullmatch(value.strip())
    if match is None or size <= 0:
        raise AppError(ErrorCode.RANGE_NOT_SATISFIABLE, 416)
    start_text, end_text = match.groups()
    try:
        if not start_text:
            if not end_text or int(end_text) <= 0:
                raise AppError(ErrorCode.RANGE_NOT_SATISFIABLE, 416)
            length = min(int(end_text), size)
            return size - length, size - 1
        start = int(start_text)
        end = int(end_text) if end_text else size - 1
    except ValueError:
        raise AppError(ErrorCode.RANGE_NOT_SATISFIABLE, 416) from None
    if start >= size or start > end:
        raise AppError(ErrorCode.RANGE_NOT_SATISFIABLE, 416)
    return start, min(end, size - 1)


def _etag_matches(header: str, etag: str) -> bool:
    candidates = {item.strip() for item in header.split(",")}
    return "*" in candidates or etag in candidates or f"W/{etag}" in candidates


def _strong_etag_matches(header: str, etag: str) -> bool:
    """If-Range uses strong comparison; weak validators cannot authorize a range."""
    return header.strip() == etag


class _ClosableStream(Protocol):
    def close(self) -> None:
        """Release a blocking stream."""


class _SerializedStorageStream:
    """Serialize generator next/close calls across threadpool workers.

    Client disconnects can cancel the async body while a worker is still inside
    ``next()``. A lock prevents ``close()`` from running concurrently with the
    generator, which is not thread-safe.
    """

    def __init__(self, stream: Generator[bytes, None, None]) -> None:
        self._stream = stream
        self._lock = threading.Lock()

    def __iter__(self) -> _SerializedStorageStream:
        return self

    def __next__(self) -> bytes:
        with self._lock:
            return next(self._stream)

    def close(self) -> None:
        with self._lock:
            self._stream.close()


async def _close_stream(stream: _ClosableStream) -> None:
    """Close a blocking storage iterator without stalling the event loop."""
    await run_in_threadpool(stream.close)


@router.post(
    "",
    status_code=201,
    response_model=ApiResponse[FileUploadResponse],
    operation_id="files_upload",
    responses=error_responses(400, 401, 403, 413, 422, 500, 503),
    openapi_extra={"parameters": [ORIGIN_HEADER, CSRF_HEADER]},
)
async def upload_file_endpoint(
    request: Request,
    file: UploadDep,
    identity: CsrfIdentityDep,
    db: SessionDep,
) -> ApiResponse[FileUploadResponse]:
    data = await file.read(request.app.state.file_max_bytes + 1)
    record = await upload_file(
        db,
        storage_from_request(request),
        actor_id=identity.user.id,
        permissions=identity.principal.permissions,
        filename=file.filename or "",
        data=data,
        request_id=request.state.request_id,
        max_bytes=request.app.state.file_max_bytes,
        scan_enabled=request.app.state.file_malware_scan_enabled,
        clamd_socket=request.app.state.file_clamd_socket,
    )
    return success(
        FileUploadResponse(
            id=record.id,
            name=record.original_name,
            size=record.size,
            sha256=record.sha256,
        ),
        request.state.request_id,
    )


@router.get(
    "",
    response_model=ApiResponse[Page[FileMetadataResponse]],
    operation_id="files_list",
    responses=error_responses(401, 403, 422, 500, 503),
)
async def list_files(
    request: Request,
    identity: IdentityDep,
    db: SessionDep,
    page: PageDep,
) -> ApiResponse[Page[FileMetadataResponse]]:
    result = await page_file_metadata(
        db,
        actor_id=identity.user.id,
        permissions=identity.principal.permissions,
        page=page,
    )
    return success(result, request.state.request_id)


@router.get(
    "/{file_id}/metadata",
    response_model=ApiResponse[FileMetadataResponse],
    operation_id="files_get_metadata",
    responses=error_responses(401, 403, 404, 422, 500, 503),
)
async def get_file_metadata(
    file_id: int,
    request: Request,
    identity: IdentityDep,
    db: SessionDep,
) -> ApiResponse[FileMetadataResponse]:
    record = await authorized_record(
        db,
        file_id=file_id,
        actor_id=identity.user.id,
        permissions=identity.principal.permissions,
        action="read",
        request_id=request.state.request_id,
    )
    return success(to_file_metadata(record), request.state.request_id)


@router.get(
    "/{file_id}",
    response_class=Response,
    operation_id="files_download",
    responses={
        200: {
            "content": {"application/octet-stream": {}},
            "description": "Binary file content",
            "headers": DOWNLOAD_RESPONSE_HEADERS,
        },
        206: {
            "description": "Partial binary content",
            "headers": RANGE_RESPONSE_HEADERS,
        },
        304: {"description": "Entity not modified", "headers": DOWNLOAD_RESPONSE_HEADERS},
        **error_responses(401, 403, 404, 416, 422, 500, 503),
    },
    openapi_extra={"parameters": [RANGE_HEADER, IF_RANGE_HEADER, IF_NONE_MATCH_HEADER]},
)
async def download_file_endpoint(
    file_id: int,
    request: Request,
    identity: IdentityDep,
    db: SessionDep,
) -> Response:
    record = await authorized_record(
        db,
        file_id=file_id,
        actor_id=identity.user.id,
        permissions=identity.principal.permissions,
        action="read",
        request_id=request.state.request_id,
    )
    etag = f'"{record.sha256}"'
    headers = _content_headers(record.original_name, etag)
    if _etag_matches(request.headers.get("if-none-match", ""), etag):
        return Response(status_code=304, headers=headers)
    range_header = request.headers.get("range")
    if_range = request.headers.get("if-range")
    if range_header and if_range and not _strong_etag_matches(if_range, etag):
        range_header = None
    if range_header:
        try:
            start, end = _parse_range(range_header, record.size)
        except AppError as exc:
            if exc.code != str(ErrorCode.RANGE_NOT_SATISFIABLE):
                raise
            return error_response(
                request,
                str(ErrorCode.RANGE_NOT_SATISFIABLE),
                416,
                [{"field": "Range", "reason": "not satisfiable"}],
                headers={
                    **headers,
                    "Content-Range": f"bytes */{record.size}",
                },
            )
        status_code = 206
        length = end - start + 1
        headers["Content-Range"] = f"bytes {start}-{end}/{record.size}"
    else:
        start, length, status_code = 0, record.size, 200
    headers["Content-Length"] = str(length)
    storage = storage_from_request(request)
    try:
        stream = _SerializedStorageStream(
            storage.iter_chunks(record.object_key, offset=start, length=length)
        )
        first = await run_in_threadpool(next, stream, None)
    except (ValueError, OSError):
        raise AppError(ErrorCode.NOT_FOUND, 404) from None
    if first is None:
        await _close_stream(stream)
        raise AppError(ErrorCode.NOT_FOUND, 404)
    try:
        await record_download(
            db,
            file_id=file_id,
            actor_id=identity.user.id,
            request_id=request.state.request_id,
        )
    except Exception:
        await _close_stream(stream)
        raise

    async def body() -> AsyncIterator[bytes]:
        try:
            yield first
            async for chunk in iterate_in_threadpool(stream):
                yield chunk
        finally:
            await _close_stream(stream)

    return StreamingResponse(
        body(),
        status_code=status_code,
        media_type="application/octet-stream",
        headers=headers,
    )


@router.delete(
    "/{file_id}",
    response_model=ApiResponse[FileDeleteResponse],
    operation_id="files_delete",
    responses=error_responses(401, 403, 404, 422, 500, 503),
    openapi_extra={"parameters": [ORIGIN_HEADER, CSRF_HEADER]},
)
async def delete_file_endpoint(
    file_id: int,
    request: Request,
    identity: CsrfIdentityDep,
    db: SessionDep,
) -> ApiResponse[FileDeleteResponse]:
    await delete_file(
        db,
        storage_from_request(request),
        file_id=file_id,
        actor_id=identity.user.id,
        permissions=identity.principal.permissions,
        request_id=request.state.request_id,
    )
    return success(FileDeleteResponse(deleted=True), request.state.request_id)
