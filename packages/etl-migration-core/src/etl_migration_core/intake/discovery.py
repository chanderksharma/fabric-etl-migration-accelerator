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

from etl_migration_core.contracts.ir import SourcePlatform
from etl_migration_core.intake.domain import (
    SUPPORTED_EXTENSIONS,
    DiscoveryLimits,
    DiscoverySummary,
    InputKind,
    SkippedItem,
    SkipReason,
    WorkflowCandidate,
    classify_input,
)
from etl_migration_core.sources.base import SourceAdapter, SourceFileDiscoveryAdapter, SourceMatch
from etl_migration_core.sources.registry import (
    DetectedSource,
    SourceAdapterRegistry,
)

IDMC_ADAPTER_ID = "informatica-idmc"
ALTERYX_ADAPTER_ID = "alteryx"


class InputRejectedError(ValueError):
    """Raised when an untrusted input violates a security boundary."""

    def __init__(self, path: str, reason: SkipReason, detail: str) -> None:
        super().__init__(detail)
        self.path = path
        self.reason = reason
        self.detail = detail


class DiscoveryService:
    """Discover unique workflows without executing their content.

    Built-in adapters are always available, so an injected registry only adds plugins and
    candidate metadata never depends on how the service was constructed.
    """

    def __init__(
        self,
        limits: DiscoveryLimits | None = None,
        source_registry: SourceAdapterRegistry | None = None,
    ) -> None:
        # Imported here because the built-in adapters import archive helpers from this module.
        from etl_migration_core.sources.defaults import with_builtin_adapters

        self._limits = limits or DiscoveryLimits()
        self._source_registry = with_builtin_adapters(source_registry)
        self._claimed_extensions = self._source_registry.file_extensions()

    def _adapter(self, adapter_id: str) -> SourceAdapter:
        adapter = self._source_registry.get(adapter_id)
        if adapter is None:
            raise LookupError(f"Built-in source adapter is not registered: {adapter_id}")
        return adapter

    def _candidate(
        self,
        *,
        source_path: str,
        display_path: str,
        extension: str,
        size_bytes: int,
        sha256: str,
        detected: DetectedSource | None = None,
        builtin_adapter_id: str = ALTERYX_ADAPTER_ID,
        asset_type: str = "workflow",
        archive_chain: tuple[str, ...] = (),
    ) -> WorkflowCandidate:
        """Build a candidate whose identity always comes from an adapter, never from defaults."""
        adapter = detected.adapter if detected else self._adapter(builtin_adapter_id)
        match: SourceMatch | None = detected.match if detected else None
        return WorkflowCandidate(
            source_path=source_path,
            display_path=display_path,
            extension=extension,
            size_bytes=size_bytes,
            sha256=sha256,
            archive_path="!".join(archive_chain) or None,
            archive_chain=archive_chain,
            source_platform=match.platform if match else adapter.platform,
            source_product=match.product if match else adapter.product,
            asset_type=match.asset_type if match else asset_type,
            adapter_id=adapter.adapter_id,
            adapter_version=adapter.adapter_version,
            parser_version=adapter.parser_version,
            registry_version=adapter.registry_version,
            rules_version=adapter.rules_version,
        )

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
        if extension not in SUPPORTED_EXTENSIONS and extension not in self._claimed_extensions:
            skipped.append(
                SkippedItem(
                    display_path,
                    SkipReason.UNSUPPORTED_EXTENSION,
                    extension or "no extension",
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
        detected: DetectedSource | None = None
        try:
            if extension == ".xml" or extension not in SUPPORTED_EXTENSIONS:
                detected = self._detect_claimed(path, extension, display_path)
            digest = self._stream_digest(path.open("rb"))
        except ValueError as error:
            skipped.append(SkippedItem(display_path, SkipReason.UNSUPPORTED_INPUT, str(error)))
            return
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
            self._candidate(
                source_path=str(path),
                display_path=display_path,
                extension=extension,
                size_bytes=size,
                sha256=digest,
                detected=detected,
            )
        )

    def _detect(self, source: Path | bytes, extension: str, display_path: str) -> DetectedSource:
        """Detect a claimed format from a file or from archive-member bytes."""
        if isinstance(source, Path):
            return self._source_registry.detect(source, display_path)
        if self._source_registry.supports_stream_probe(extension):
            return self._source_registry.detect_bytes(source, display_path)
        with tempfile.TemporaryDirectory(prefix="source-discovery-") as directory:
            staged = Path(directory) / f"source{extension}"
            staged.write_bytes(source)
            return self._source_registry.detect(staged, display_path)

    def _detect_claimed(
        self, source: Path | bytes, extension: str, display_path: str
    ) -> DetectedSource:
        """Detect XML or a plugin-claimed extension, validating plugin declarations."""
        detected = self._detect(source, extension, display_path)
        if extension != ".xml":
            self._validate_plugin_detection(detected, extension)
        return detected

    @staticmethod
    def _validate_plugin_detection(
        detected: DetectedSource, extension: str
    ) -> DetectedSource:
        if (
            not isinstance(detected.adapter, SourceFileDiscoveryAdapter)
            or extension not in detected.adapter.supported_extensions
        ):
            raise ValueError("Selected source adapter does not declare this extension")
        if isinstance(detected.match.platform, SourcePlatform):
            raise ValueError("Plugin file extension cannot claim a built-in source identity")
        if not all(
            isinstance(version, str) and version.strip()
            for version in (
                detected.adapter.adapter_version,
                detected.adapter.parser_version,
                detected.adapter.registry_version,
                detected.adapter.rules_version,
            )
        ):
            raise ValueError("Source adapter version metadata must not be empty")
        return detected

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
            self._candidate(
                source_path=str(archive),
                display_path=archive.name,
                extension=".zip",
                size_bytes=size,
                sha256=digest,
                builtin_adapter_id=IDMC_ADAPTER_ID,
                asset_type="export_package",
            )
        )

    def _discover_idmc_directory(
        self,
        root: Path,
        candidates: list[WorkflowCandidate],
        skipped: list[SkippedItem],
        seen_hashes: dict[str, str],
    ) -> None:
        value, size = hash_idmc_directory(root, limits=self._limits)
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
            self._candidate(
                source_path=str(root),
                display_path=root.name,
                extension=".idmc",
                size_bytes=size,
                sha256=value,
                builtin_adapter_id=IDMC_ADAPTER_ID,
                asset_type="export_package",
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
            claimed = extension in self._claimed_extensions and extension != ".zip"
            if (extension not in SUPPORTED_EXTENSIONS and not claimed) or extension == ".yxzp":
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
            display_path = "!".join((*chain, entry.filename))
            detected: DetectedSource | None = None
            if extension == ".xml" or extension not in SUPPORTED_EXTENSIONS:
                try:
                    detected = self._detect_claimed(content, extension, display_path)
                except ValueError as error:
                    skipped.append(
                        SkippedItem(display_path, SkipReason.UNSUPPORTED_INPUT, str(error))
                    )
                    continue
                except OSError as error:
                    skipped.append(
                        SkippedItem(display_path, SkipReason.UNREADABLE_INPUT, type(error).__name__)
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
                self._candidate(
                    source_path=str(archive),
                    display_path=display_path,
                    extension=extension,
                    size_bytes=entry.file_size,
                    sha256=digest,
                    detected=detected,
                    archive_chain=(*chain, entry.filename),
                )
            )

    def _stream_digest(self, stream: IO[bytes]) -> str:
        return _hash_stream(stream)

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
        validate_archive_entries(archive, entries, self._limits)

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


def hash_idmc_directory(
    root: Path, *, limits: DiscoveryLimits | None = None, destination: Path | None = None
) -> tuple[str, int]:
    """Hash and optionally copy a bounded IDMC directory without following links."""
    bounds = limits or DiscoveryLimits()
    files: list[Path] = []
    directories: list[Path] = []

    def unreadable(error: OSError) -> None:
        raise InputRejectedError(
            str(error.filename or root), SkipReason.UNREADABLE_INPUT, type(error).__name__
        ) from error

    if _is_link(root) or not root.is_dir():
        raise InputRejectedError(str(root), SkipReason.SYMBOLIC_LINK, "Invalid directory root")
    for current, child_dirs, child_files in os.walk(root, followlinks=False, onerror=unreadable):
        base = Path(current)
        for name in (*child_dirs, *child_files):
            path = base / name
            if _is_link(path):
                raise InputRejectedError(str(path), SkipReason.SYMBOLIC_LINK, "Link not accepted")
        directories.extend(base / name for name in child_dirs)
        files.extend(base / name for name in child_files)
        if len(files) + len(directories) > bounds.max_archive_entries:
            raise InputRejectedError(
                str(root), SkipReason.ARCHIVE_ENTRY_LIMIT, "IDMC directory exceeds entry limit"
            )
    if destination is not None:
        destination.mkdir(parents=True, exist_ok=False)
        for directory in directories:
            (destination / directory.relative_to(root)).mkdir(parents=True, exist_ok=True)
    digest = hashlib.sha256()
    size = 0
    for path in sorted(files, key=lambda item: str(item.relative_to(root)).casefold()):
        if _is_link(path) or not path.is_file():
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
                        "IDMC directory exceeds size limit",
                    )
                if file_size > bounds.max_file_bytes:
                    raise InputRejectedError(
                        str(path),
                        SkipReason.FILE_TOO_LARGE,
                        "IDMC directory file exceeds size limit",
                    )
                digest.update(chunk)
                if output is not None:
                    output.write(chunk)
    return digest.hexdigest(), size


def _hash_stream(stream: IO[bytes]) -> str:
    digest = hashlib.sha256()
    with stream:
        while chunk := stream.read(1024 * 1024):
            digest.update(chunk)
    return digest.hexdigest()
