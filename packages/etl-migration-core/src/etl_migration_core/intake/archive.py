"""Pure archive safety, member-path validation, and bounded directory hashing.

Kept free of source-adapter imports so both ``DiscoveryService`` and source
adapters can depend on it without circular imports.
"""

from __future__ import annotations

import hashlib
import os
import stat
import zipfile
from contextlib import ExitStack
from pathlib import Path, PurePosixPath

from etl_migration_core.intake.domain import DiscoveryLimits, SkipReason


class InputRejectedError(ValueError):
    """Raised when an untrusted input violates a security boundary."""

    def __init__(self, path: str, reason: SkipReason, detail: str) -> None:
        super().__init__(detail)
        self.path = path
        self.reason = reason
        self.detail = detail


def validate_archive_entries(
    archive: Path,
    entries: list[zipfile.ZipInfo],
    limits: DiscoveryLimits,
) -> set[str]:
    """Validate ZIP entry counts, paths, compression ratios, and expansion limits."""
    if len(entries) > limits.max_archive_entries:
        raise InputRejectedError(
            str(archive),
            SkipReason.ARCHIVE_ENTRY_LIMIT,
            f"{len(entries)} entries exceeds {limits.max_archive_entries}",
        )
    expanded_size = sum(entry.file_size for entry in entries)
    if expanded_size > limits.max_archive_uncompressed_bytes:
        raise InputRejectedError(
            str(archive),
            SkipReason.ARCHIVE_SIZE_LIMIT,
            f"{expanded_size} bytes exceeds {limits.max_archive_uncompressed_bytes}",
        )
    names: set[str] = set()
    for entry in entries:
        validate_member_path(archive, entry.filename)
        normalized = str(PurePosixPath(entry.filename.replace("\\", "/"))).casefold()
        if (
            normalized in names
            or entry.flag_bits & 1
            or stat.S_ISLNK(entry.external_attr >> 16)
        ):
            raise InputRejectedError(
                entry.filename,
                SkipReason.INVALID_ARCHIVE,
                "Colliding, encrypted, or linked archive entry",
            )
        names.add(normalized)
        compressed = max(entry.compress_size, 1)
        ratio = entry.file_size / compressed
        if ratio > limits.max_compression_ratio:
            raise InputRejectedError(
                entry.filename,
                SkipReason.ARCHIVE_RATIO_LIMIT,
                f"Compression ratio {ratio:.1f} exceeds {limits.max_compression_ratio}",
            )
    return names


def validate_member_path(archive: Path, member_name: str) -> PurePosixPath:
    """Reject archive member paths that escape the extraction sandbox."""
    normalized = PurePosixPath(member_name.replace("\\", "/"))
    if (
        not normalized.parts
        or normalized.is_absolute()
        or ".." in normalized.parts
        or any(
            ":" in part
            or part.endswith((".", " "))
            or "\x00" in part
            or part.split(".", 1)[0].upper()
            in {
                "CON",
                "PRN",
                "AUX",
                "NUL",
                *(f"COM{index}" for index in range(1, 10)),
                *(f"LPT{index}" for index in range(1, 10)),
            }
            for part in normalized.parts
        )
    ):
        raise InputRejectedError(
            f"{archive}!{member_name}",
            SkipReason.ARCHIVE_PATH_TRAVERSAL,
            "Archive member escapes the extraction sandbox",
        )
    return normalized


def is_link(path: Path) -> bool:
    """Return True for symlinks and Windows reparse points."""
    if path.is_symlink():
        return True
    if not path.exists():
        return False
    return bool(getattr(path.stat(follow_symlinks=False), "st_file_attributes", 0) & 0x400)


def hash_directory(
    root: Path, *, limits: DiscoveryLimits | None = None, destination: Path | None = None
) -> tuple[str, int]:
    """Hash and optionally copy a bounded export directory without following links."""
    bounds = limits or DiscoveryLimits()
    files: list[Path] = []
    directories: list[Path] = []

    def unreadable(error: OSError) -> None:
        raise InputRejectedError(
            str(error.filename or root), SkipReason.UNREADABLE_INPUT, type(error).__name__
        ) from error

    if is_link(root) or not root.is_dir():
        raise InputRejectedError(str(root), SkipReason.SYMBOLIC_LINK, "Invalid directory root")
    for current, child_dirs, child_files in os.walk(root, followlinks=False, onerror=unreadable):
        base = Path(current)
        for name in (*child_dirs, *child_files):
            path = base / name
            if is_link(path):
                raise InputRejectedError(str(path), SkipReason.SYMBOLIC_LINK, "Link not accepted")
        directories.extend(base / name for name in child_dirs)
        files.extend(base / name for name in child_files)
        if len(files) + len(directories) > bounds.max_archive_entries:
            raise InputRejectedError(
                str(root), SkipReason.ARCHIVE_ENTRY_LIMIT, "Export directory exceeds entry limit"
            )
    if destination is not None:
        destination.mkdir(parents=True, exist_ok=False)
        for directory in directories:
            (destination / directory.relative_to(root)).mkdir(parents=True, exist_ok=True)
    digest = hashlib.sha256()
    size = 0
    for path in sorted(files, key=lambda item: str(item.relative_to(root)).casefold()):
        if is_link(path) or not path.is_file():
            raise InputRejectedError(str(path), SkipReason.SYMBOLIC_LINK, "Invalid directory entry")
        relative = path.relative_to(root)
        digest.update(relative.as_posix().encode("utf-8"))
        with path.open("rb") as source, ExitStack() as stack:
            output = (
                stack.enter_context((destination / relative).open("wb"))
                if destination is not None
                else None
            )
            file_size = 0
            while chunk := source.read(1024 * 1024):
                size += len(chunk)
                file_size += len(chunk)
                if size > bounds.max_archive_uncompressed_bytes:
                    raise InputRejectedError(
                        str(root),
                        SkipReason.ARCHIVE_SIZE_LIMIT,
                        "Export directory exceeds size limit",
                    )
                if file_size > bounds.max_file_bytes:
                    raise InputRejectedError(
                        str(path),
                        SkipReason.FILE_TOO_LARGE,
                        "Export directory file exceeds size limit",
                    )
                digest.update(chunk)
                if output is not None:
                    output.write(chunk)
    return digest.hexdigest(), size


hash_idmc_directory = hash_directory
