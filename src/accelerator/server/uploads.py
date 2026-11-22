"""Bounded staging of browser uploads into a private sandbox directory."""

from __future__ import annotations

from pathlib import Path, PurePosixPath

from fastapi import HTTPException, UploadFile
from starlette.concurrency import run_in_threadpool

from etl_migration_core.intake.discovery import InputRejectedError, validate_member_path

MAX_BROWSER_UPLOAD_BYTES = 100 * 1024 * 1024
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


def safe_upload_path(filename: str | None) -> PurePosixPath:
    """Reject empty, absolute, traversing, or otherwise unsafe client-supplied names."""
    if not filename:
        raise HTTPException(status_code=400, detail="An uploaded file has no name")
    try:
        return validate_member_path(Path("upload"), filename)
    except InputRejectedError as error:
        raise HTTPException(status_code=400, detail=error.detail) from error
