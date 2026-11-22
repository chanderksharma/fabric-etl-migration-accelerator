"""Bounded staging of browser uploads into a private sandbox directory."""

from __future__ import annotations

from collections.abc import Callable, Coroutine
from pathlib import Path, PurePosixPath
from typing import Any

from fastapi import HTTPException, UploadFile
from fastapi.routing import APIRoute

# Starlette types this wrapper in a private module and does not re-export it.
from starlette._utils import AwaitableOrContextManager
from starlette.concurrency import run_in_threadpool
from starlette.datastructures import FormData
from starlette.requests import Request
from starlette.responses import Response

from etl_migration_core.intake.discovery import InputRejectedError, validate_member_path

MAX_BROWSER_UPLOAD_BYTES = 100 * 1024 * 1024
MAX_UPLOAD_FILES = 10_000
_CHUNK_BYTES = 1024 * 1024


async def stage_uploads(files: list[UploadFile], sandbox: Path) -> list[Path]:
    """Write each upload under ``sandbox`` with validated names and a total size cap."""
    staged: list[Path] = []
    total_size = 0
    seen_names: set[str] = set()
    for upload in files:
        relative_path = safe_upload_path(upload.filename)
        key = str(relative_path).casefold()
        if key in seen_names:
            raise HTTPException(status_code=400, detail="Uploaded names collide")
        seen_names.add(key)
        destination = sandbox.joinpath(*relative_path.parts)
        destination.parent.mkdir(parents=True, exist_ok=True)
        size = 0
        with destination.open("wb") as target:
            while chunk := await upload.read(_CHUNK_BYTES):
                size += len(chunk)
                total_size += len(chunk)
                if size > MAX_BROWSER_UPLOAD_BYTES or total_size > MAX_BROWSER_UPLOAD_BYTES:
                    raise HTTPException(
                        status_code=413,
                        detail=f"{upload.filename} exceeds the browser upload limit",
                    )
                await run_in_threadpool(target.write, chunk)
        staged.append(destination)
    return staged


class BoundedUploadRequest(Request):
    """Raise only the multipart file cap. Part size and field count stay at Starlette defaults."""

    def form(
        self,
        *,
        max_files: int | float = MAX_UPLOAD_FILES,
        max_fields: int | float = 1000,
        max_part_size: int = 1024 * 1024,
    ) -> AwaitableOrContextManager[FormData]:
        return super().form(
            max_files=max_files,
            max_fields=max_fields,
            max_part_size=max_part_size,
        )


class BoundedUploadRoute(APIRoute):
    """Give every route a request whose form parser allows a folder-sized upload."""

    def get_route_handler(self) -> Callable[[Request], Coroutine[Any, Any, Response]]:
        original = super().get_route_handler()

        async def handler(request: Request) -> Response:
            bounded = BoundedUploadRequest(request.scope, request.receive, request._send)
            return await original(bounded)

        return handler


def safe_upload_path(filename: str | None) -> PurePosixPath:
    """Reject empty, absolute, traversing, or otherwise unsafe client-supplied names."""
    if not filename:
        raise HTTPException(status_code=400, detail="An uploaded file has no name")
    try:
        return validate_member_path(Path("upload"), filename)
    except InputRejectedError as error:
        raise HTTPException(status_code=400, detail=error.detail) from error
