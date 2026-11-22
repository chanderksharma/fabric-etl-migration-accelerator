"""Bounded file reads shared by built-in and plugin source adapters."""

from __future__ import annotations

from pathlib import Path


class SourceTooLargeError(ValueError):
    """A source file exceeds the size limit declared by its adapter."""


class SourceChangedError(ValueError):
    """A source file grew while it was being read."""


def read_bounded(path: Path, limit: int) -> bytes:
    """Read one file completely, failing closed when it exceeds ``limit`` bytes.

    The read length comes from the real file size. CPython preallocates the requested
    length, so ``read(limit + 1)`` costs about ``limit`` bytes for every file, however small.
    A file that grows after it was measured is rejected instead of returning a partial read.
    """
    size = path.stat().st_size
    if size > limit:
        raise SourceTooLargeError(f"{path.name} is {size} bytes, above the {limit} byte limit")
    with path.open("rb") as stream:
        content = stream.read(size + 1)
    if len(content) > size:
        raise SourceChangedError(f"{path.name} changed while it was being read")
    return content
