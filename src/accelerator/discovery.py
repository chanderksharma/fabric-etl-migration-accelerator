"""Secure workflow discovery for files, folders, and ZIP archives."""

from __future__ import annotations

import hashlib
import io
import os
import shutil
import stat
import tempfile
import zipfile
from collections.abc import Iterator
from contextlib import ExitStack, contextmanager
from pathlib import Path, PurePosixPath
from typing import IO

from accelerator.domain import (
    SUPPORTED_EXTENSIONS,
    DiscoveryLimits,
    DiscoverySummary,
    InputKind,
    SkippedItem,
    SkipReason,
    WorkflowCandidate,
    classify_input,
)
from accelerator.etl_ir import SourcePlatform
from accelerator.sources.informatica_powercenter import PowerCenterSourceAdapter


class InputRejectedError(ValueError):
    """Raised when an untrusted input violates a security boundary."""

    def __init__(self, path: str, reason: SkipReason, detail: str) -> None:
        super().__init__(detail)
        self.path = path
        self.reason = reason
        self.detail = detail


class DiscoveryService:
    """Discover unique workflows without executing their content."""

    def __init__(self, limits: DiscoveryLimits | None = None) -> None:
        self._limits = limits or DiscoveryLimits()

    def discover(self, input_path: Path) -> DiscoverySummary:
        """Discover workflows and produce a deterministic pre-run summary."""
        if str(input_path).startswith(("\\\\", "//")):
            raise InputRejectedError(
                str(input_path), SkipReason.UNSUPPORTED_INPUT, "UNC inputs are not accepted"
            )
        path = input_path.expanduser().absolute()
        try:
            linked = any(_is_link(parent) for parent in (path, *path.parents))
        except OSError as error:
            raise InputRejectedError(
                str(path), SkipReason.UNREADABLE_INPUT, type(error).__name__
            ) from error
        if linked:
            raise InputRejectedError(
                str(path), SkipReason.SYMBOLIC_LINK, "Linked input paths are not accepted"
            )
        try:
            input_kind = classify_input(path)
        except ValueError as error:
            reason = SkipReason.MISSING_PATH if not path.exists() else SkipReason.UNSUPPORTED_INPUT
            raise InputRejectedError(str(path), reason, str(error)) from error
        except OSError as error:
            raise InputRejectedError(
                str(path), SkipReason.UNREADABLE_INPUT, type(error).__name__
            ) from error

        candidates: list[WorkflowCandidate] = []
        skipped: list[SkippedItem] = []
        seen_hashes: dict[str, str] = {}
        budget = [0, 0, 0]

        if input_kind is InputKind.ZIP or path.suffix.casefold() == ".yxzp":
            self._discover_zip(path, candidates, skipped, seen_hashes, budget)
        elif input_kind is InputKind.FOLDER:
            if (path / "manifest.json").is_file() and (path / "Explore").is_dir():
                self._discover_idmc_directory(path, candidates, skipped, seen_hashes)
            else:
                self._discover_folder(path, candidates, skipped, seen_hashes, budget)
        else:
            self._discover_file(path, candidates, skipped, seen_hashes)

        ordered_candidates = tuple(
            sorted(candidates, key=lambda item: item.display_path.casefold())
        )
        ordered_skipped = tuple(
            sorted(skipped, key=lambda item: (item.path.casefold(), item.reason.value))
        )
        return DiscoverySummary(
            input_path=str(path),
            input_kind=input_kind,
            workflows=ordered_candidates,
            skipped=ordered_skipped,
            total_size_bytes=sum(item.size_bytes for item in ordered_candidates),
        )

    def _discover_folder(
        self,
        root: Path,
        candidates: list[WorkflowCandidate],
        skipped: list[SkippedItem],
        seen_hashes: dict[str, str],
        budget: list[int],
    ) -> None:
        def unreadable(error: OSError) -> None:
            skipped.append(
                SkippedItem(
                    str(error.filename or root),
                    SkipReason.UNREADABLE_INPUT,
                    type(error).__name__,
                )
            )

        for directory, directories, files in os.walk(root, followlinks=False, onerror=unreadable):
            base = Path(directory)
            for name in list(directories):
                try:
                    linked = _is_link(base / name)
                except OSError as error:
                    directories.remove(name)
                    unreadable(error)
                    continue
                if linked:
                    directories.remove(name)
                    skipped.append(
                        SkippedItem(str(base / name), SkipReason.SYMBOLIC_LINK, "Link skipped")
                    )
            directories.sort(key=str.casefold)
            for name in sorted(files, key=str.casefold):
                path = base / name
                try:
                    linked = _is_link(path)
                except OSError as error:
                    unreadable(error)
                    continue
                if linked:
                    skipped.append(SkippedItem(str(path), SkipReason.SYMBOLIC_LINK, "Link skipped"))
                    continue
                if path.suffix.casefold() in {".zip", ".yxzp"}:
                    self._discover_zip(path, candidates, skipped, seen_hashes, budget)
                    continue
                self._discover_file(path, candidates, skipped, seen_hashes, relative_to=root)

    def _discover_file(
        self,
        path: Path,
        candidates: list[WorkflowCandidate],
        skipped: list[SkippedItem],
        seen_hashes: dict[str, str],
        *,
        relative_to: Path | None = None,
    ) -> None:
        display_path = str(path.relative_to(relative_to)) if relative_to else path.name
        extension = path.suffix.casefold()
        if extension not in SUPPORTED_EXTENSIONS:
            skipped.append(
                SkippedItem(
                    display_path,
                    SkipReason.UNSUPPORTED_EXTENSION,
                    extension or "no extension",
                )
            )
            return
        if extension == ".xml" and b"<POWERMART" not in path.read_bytes()[:64_000]:
            skipped.append(
                SkippedItem(
                    display_path,
                    SkipReason.UNSUPPORTED_INPUT,
                    "XML input is not a PowerCenter repository export",
                )
            )
            return
        try:
            size = path.stat().st_size
        except OSError as error:
            skipped.append(
                SkippedItem(display_path, SkipReason.UNREADABLE_INPUT, type(error).__name__)
            )
            return
        if size > self._limits.max_file_bytes:
            skipped.append(
                SkippedItem(
                    display_path,
                    SkipReason.FILE_TOO_LARGE,
                    f"{size} bytes exceeds {self._limits.max_file_bytes}",
                )
            )
            return
        try:
            digest = _hash_stream(path.open("rb"))
        except OSError as error:
            skipped.append(
                SkippedItem(display_path, SkipReason.UNREADABLE_INPUT, type(error).__name__)
            )
            return
        duplicate = seen_hashes.get(digest)
        if duplicate is not None:
            skipped.append(
                SkippedItem(
                    display_path,
                    SkipReason.DUPLICATE_CONTENT,
                    f"Content matches {duplicate}",
                )
            )
            return
        seen_hashes[digest] = display_path
        candidates.append(
            WorkflowCandidate(
                source_path=str(path),
                display_path=display_path,
                extension=extension,
                size_bytes=size,
                sha256=digest,
                source_platform=(
                    SourcePlatform.INFORMATICA_POWERCENTER
                    if extension == ".xml"
                    else SourcePlatform.ALTERYX
                ),
                source_product=(
                    "Informatica PowerCenter"
                    if extension == ".xml"
                    else "Alteryx Designer"
                ),
                asset_type=(
                    "repository_export" if extension == ".xml" else "workflow"
                ),
                adapter_id=(
                    "informatica-powercenter" if extension == ".xml" else "alteryx"
                ),
                adapter_version=(
                    PowerCenterSourceAdapter.adapter_version
                    if extension == ".xml"
                    else "1.0.0"
                ),
            )
        )

    def _discover_zip(
        self,
        archive: Path,
        candidates: list[WorkflowCandidate],
        skipped: list[SkippedItem],
        seen_hashes: dict[str, str],
        budget: list[int],
    ) -> None:
        try:
            with zipfile.ZipFile(archive) as package:
                if _looks_like_idmc_package(package):
                    self._add_idmc_archive_candidate(
                        archive,
                        package,
                        candidates,
                        skipped,
                        seen_hashes,
                    )
                    return
                self._scan_package(package, archive, (), candidates, skipped, seen_hashes, budget)
        except (zipfile.BadZipFile, RuntimeError, EOFError) as error:
            raise InputRejectedError(
                str(archive), SkipReason.INVALID_ARCHIVE, "The ZIP archive is invalid"
            ) from error

    def _add_idmc_archive_candidate(
        self,
        archive: Path,
        package: zipfile.ZipFile,
        candidates: list[WorkflowCandidate],
        skipped: list[SkippedItem],
        seen_hashes: dict[str, str],
    ) -> None:
        entries = package.infolist()
        self._validate_archive(archive, entries)
        size = archive.stat().st_size
        if size > self._limits.max_archive_uncompressed_bytes:
            raise InputRejectedError(
                str(archive),
                SkipReason.ARCHIVE_SIZE_LIMIT,
                "IDMC export package exceeds the archive size limit",
            )
        digest = _hash_stream(archive.open("rb"))
        duplicate = seen_hashes.get(digest)
        if duplicate is not None:
            skipped.append(
                SkippedItem(
                    archive.name,
                    SkipReason.DUPLICATE_CONTENT,
                    f"Content matches {duplicate}",
                )
            )
            return
        seen_hashes[digest] = archive.name
        candidates.append(
            WorkflowCandidate(
                source_path=str(archive),
                display_path=archive.name,
                extension=".zip",
                size_bytes=size,
                sha256=digest,
                source_platform=SourcePlatform.INFORMATICA_IDMC,
                source_product="Informatica IDMC",
                asset_type="export_package",
                adapter_id="informatica-idmc",
            )
        )

    def _discover_idmc_directory(
        self,
        root: Path,
        candidates: list[WorkflowCandidate],
        skipped: list[SkippedItem],
        seen_hashes: dict[str, str],
    ) -> None:
        files = sorted(
            (path for path in root.rglob("*") if path.is_file()),
            key=lambda path: str(path.relative_to(root)).casefold(),
        )
        size = sum(path.stat().st_size for path in files)
        if size > self._limits.max_archive_uncompressed_bytes:
            raise InputRejectedError(
                str(root),
                SkipReason.ARCHIVE_SIZE_LIMIT,
                "IDMC export directory exceeds the archive size limit",
            )
        digest = hashlib.sha256()
        for path in files:
            relative = path.relative_to(root).as_posix()
            digest.update(relative.encode("utf-8"))
            digest.update(path.read_bytes())
        value = digest.hexdigest()
        duplicate = seen_hashes.get(value)
        if duplicate is not None:
            skipped.append(
                SkippedItem(
                    root.name,
                    SkipReason.DUPLICATE_CONTENT,
                    f"Content matches {duplicate}",
                )
            )
            return
        seen_hashes[value] = root.name
        candidates.append(
            WorkflowCandidate(
                source_path=str(root),
                display_path=root.name,
                extension=".idmc",
                size_bytes=size,
                sha256=value,
                source_platform=SourcePlatform.INFORMATICA_IDMC,
                source_product="Informatica IDMC",
                asset_type="export_package",
                adapter_id="informatica-idmc",
            )
        )

    def _scan_package(
        self,
        package: zipfile.ZipFile,
        archive: Path,
        chain: tuple[str, ...],
        candidates: list[WorkflowCandidate],
        skipped: list[SkippedItem],
        seen_hashes: dict[str, str],
        budget: list[int],
    ) -> None:
        entries = package.infolist()
        self._validate_archive(archive, entries)
        budget[0] += len(entries)
        if budget[0] > self._limits.max_archive_entries:
            raise InputRejectedError(
                str(archive), SkipReason.ARCHIVE_ENTRY_LIMIT, "Aggregate entry limit exceeded"
            )
        names: set[str] = set()
        for entry in sorted(entries, key=lambda item: item.filename.casefold()):
            safe_path = validate_member_path(archive, entry.filename)
            if entry.flag_bits & 1 or stat.S_ISLNK(entry.external_attr >> 16):
                raise InputRejectedError(
                    entry.filename, SkipReason.INVALID_ARCHIVE, "Encrypted or linked entry"
                )
            name_key = str(safe_path).casefold()
            if name_key in names:
                raise InputRejectedError(
                    entry.filename, SkipReason.INVALID_ARCHIVE, "Colliding archive names"
                )
            names.add(name_key)
            if entry.is_dir():
                continue
            budget[1] += entry.file_size
            if budget[1] > self._limits.max_archive_uncompressed_bytes:
                raise InputRejectedError(
                    entry.filename, SkipReason.ARCHIVE_SIZE_LIMIT, "Aggregate expansion limit"
                )
            if safe_path.suffix.casefold() == ".yxzp" and not chain:
                with package.open(entry) as stream:
                    content = self._read_member(stream, entry, budget)
                with zipfile.ZipFile(io.BytesIO(content)) as nested:
                    self._scan_package(
                        nested,
                        archive,
                        (entry.filename,),
                        candidates,
                        skipped,
                        seen_hashes,
                        budget,
                    )
                continue
            extension = safe_path.suffix.casefold()
            if extension not in SUPPORTED_EXTENSIONS or extension == ".yxzp":
                skipped.append(
                    SkippedItem(
                        entry.filename,
                        SkipReason.UNSUPPORTED_EXTENSION,
                        extension or "no extension",
                    )
                )
                continue
            if entry.file_size > self._limits.max_file_bytes:
                skipped.append(
                    SkippedItem(
                        entry.filename,
                        SkipReason.FILE_TOO_LARGE,
                        f"{entry.file_size} bytes exceeds {self._limits.max_file_bytes}",
                    )
                )
                continue
            with package.open(entry, "r") as stream:
                content = self._read_member(stream, entry, budget)
            if extension == ".xml" and b"<POWERMART" not in content[:64_000]:
                skipped.append(
                    SkippedItem(
                        entry.filename,
                        SkipReason.UNSUPPORTED_INPUT,
                        "XML input is not a PowerCenter repository export",
                    )
                )
                continue
            digest = hashlib.sha256(content).hexdigest()
            duplicate = seen_hashes.get(digest)
            if duplicate is not None:
                skipped.append(
                    SkippedItem(
                        entry.filename,
                        SkipReason.DUPLICATE_CONTENT,
                        f"Content matches {duplicate}",
                    )
                )
                continue
            seen_hashes[digest] = entry.filename
            candidates.append(
                WorkflowCandidate(
                    source_path=str(archive),
                    display_path="!".join((*chain, entry.filename)),
                    extension=extension,
                    size_bytes=entry.file_size,
                    sha256=digest,
                    archive_path="!".join((*chain, entry.filename)),
                    archive_chain=(*chain, entry.filename),
                    source_platform=(
                        SourcePlatform.INFORMATICA_POWERCENTER
                        if extension == ".xml"
                        else SourcePlatform.ALTERYX
                    ),
                    source_product=(
                        "Informatica PowerCenter"
                        if extension == ".xml"
                        else "Alteryx Designer"
                    ),
                    asset_type=(
                        "repository_export" if extension == ".xml" else "workflow"
                    ),
                    adapter_id=(
                        "informatica-powercenter" if extension == ".xml" else "alteryx"
                    ),
                    adapter_version=(
                        PowerCenterSourceAdapter.adapter_version
                        if extension == ".xml"
                        else "1.0.0"
                    ),
                )
            )

    def _read_member(
        self, stream: IO[bytes], entry: zipfile.ZipInfo, budget: list[int] | None = None
    ) -> bytes:
        content = bytearray()
        while chunk := stream.read(1024 * 1024):
            if not entry.compress_size:
                raise InputRejectedError(
                    entry.filename,
                    SkipReason.ARCHIVE_RATIO_LIMIT,
                    "Nonempty entry has zero compressed size",
                )
            content.extend(chunk)
            if budget is not None:
                budget[2] += len(chunk)
                if budget[2] > self._limits.max_archive_uncompressed_bytes:
                    raise InputRejectedError(
                        entry.filename, SkipReason.ARCHIVE_SIZE_LIMIT, "Streamed expansion limit"
                    )
            if len(content) > self._limits.max_file_bytes:
                raise InputRejectedError(
                    entry.filename, SkipReason.FILE_TOO_LARGE, "Streamed file limit exceeded"
                )
            if len(content) / max(entry.compress_size, 1) > self._limits.max_compression_ratio:
                raise InputRejectedError(
                    entry.filename, SkipReason.ARCHIVE_RATIO_LIMIT, "Streamed ratio limit exceeded"
                )
        return bytes(content)

    @contextmanager
    def staged_workflow(self, candidate: WorkflowCandidate) -> Iterator[Path]:
        """Materialize one validated archive workflow without retaining extraction trees."""
        if not candidate.archive_chain:
            yield Path(candidate.source_path)
            return
        with (
            tempfile.TemporaryDirectory(prefix="alteryx-workflow-") as directory,
            ExitStack() as stack,
        ):
            archive = stack.enter_context(zipfile.ZipFile(candidate.source_path))
            payload = b""
            for index, member in enumerate(candidate.archive_chain):
                entry = archive.getinfo(member)
                with archive.open(entry) as stream:
                    payload = self._read_member(stream, entry)
                if index < len(candidate.archive_chain) - 1:
                    archive = stack.enter_context(zipfile.ZipFile(io.BytesIO(payload)))
            destination = Path(directory) / Path(candidate.archive_chain[-1]).name
            destination.write_bytes(payload)
            yield destination

    def _validate_archive(self, archive: Path, entries: list[zipfile.ZipInfo]) -> None:
        if len(entries) > self._limits.max_archive_entries:
            raise InputRejectedError(
                str(archive),
                SkipReason.ARCHIVE_ENTRY_LIMIT,
                f"{len(entries)} entries exceeds {self._limits.max_archive_entries}",
            )
        expanded_size = sum(entry.file_size for entry in entries)
        if expanded_size > self._limits.max_archive_uncompressed_bytes:
            raise InputRejectedError(
                str(archive),
                SkipReason.ARCHIVE_SIZE_LIMIT,
                f"{expanded_size} bytes exceeds {self._limits.max_archive_uncompressed_bytes}",
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
            if ratio > self._limits.max_compression_ratio:
                raise InputRejectedError(
                    entry.filename,
                    SkipReason.ARCHIVE_RATIO_LIMIT,
                    f"Compression ratio {ratio:.1f} exceeds {self._limits.max_compression_ratio}",
                )

    @contextmanager
    def staged_zip(self, archive: Path) -> Iterator[Path]:
        """Extract a validated ZIP to a temporary sandbox and clean it up."""
        archive = archive.expanduser().resolve(strict=True)
        with zipfile.ZipFile(archive) as package:
            entries = package.infolist()
            self._validate_archive(archive, entries)
            sandbox = Path(tempfile.mkdtemp(prefix="alteryx-fabric-"))
            try:
                for entry in entries:
                    safe_path = validate_member_path(archive, entry.filename)
                    destination = sandbox.joinpath(*safe_path.parts)
                    if entry.is_dir():
                        destination.mkdir(parents=True, exist_ok=True)
                        continue
                    destination.parent.mkdir(parents=True, exist_ok=True)
                    with package.open(entry) as source, destination.open("wb") as target:
                        target.write(self._read_member(source, entry))
                yield sandbox
            finally:
                shutil.rmtree(sandbox, ignore_errors=False)


def validate_member_path(archive: Path, member_name: str) -> PurePosixPath:
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


def _looks_like_idmc_package(package: zipfile.ZipFile) -> bool:
    names = {
        PurePosixPath(entry.filename.replace("\\", "/")).as_posix().rstrip("/")
        for entry in package.infolist()
    }
    return "manifest.json" in names and any(
        name.startswith("Explore/") for name in names
    )


def _is_link(path: Path) -> bool:
    if path.is_symlink():
        return True
    if not path.exists():
        return False
    return bool(getattr(path.stat(follow_symlinks=False), "st_file_attributes", 0) & 0x400)


def _hash_stream(stream: IO[bytes]) -> str:
    digest = hashlib.sha256()
    with stream:
        while chunk := stream.read(1024 * 1024):
            digest.update(chunk)
    return digest.hexdigest()
