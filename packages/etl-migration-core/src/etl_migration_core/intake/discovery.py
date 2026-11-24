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
from etl_migration_core.intake.archive import (
    InputRejectedError,
    hash_directory,
    hash_idmc_directory,
    validate_archive_entries,
    validate_member_path,
)
from etl_migration_core.intake.archive import is_link as _is_link
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
        # Imported lazily so importing etl_migration_core.sources.defaults before
        # etl_migration_core.intake never triggers a package-init cycle.
        from etl_migration_core.sources.defaults import with_builtin_adapters

        self._limits = limits or DiscoveryLimits()
        self._source_registry = with_builtin_adapters(source_registry)
        self._claimed_extensions = self._source_registry.file_extensions()
        self._adapter_archive_extensions = self._source_registry.archive_extensions()
        self._archive_extensions = frozenset({".zip", *self._adapter_archive_extensions})

    @property
    def source_registry(self) -> SourceAdapterRegistry:
        """Return the effective source adapter registry used by discovery."""
        return self._source_registry

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

        if (
            input_kind is InputKind.ZIP
            or path.suffix.casefold() in self._adapter_archive_extensions
        ):
            self._discover_zip(path, candidates, skipped, seen_hashes, budget)
        elif input_kind is InputKind.FOLDER:
            matched_directory_adapter = self._source_registry.match_directory(path)
            if matched_directory_adapter is not None:
                self._discover_package_directory(
                    path,
                    matched_directory_adapter,
                    candidates,
                    skipped,
                    seen_hashes,
                )
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
                if path.suffix.casefold() in self._archive_extensions:
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

    def _discover_package_directory(
        self,
        root: Path,
        adapter: SourceAdapter,
        candidates: list[WorkflowCandidate],
        skipped: list[SkippedItem],
        seen_hashes: dict[str, str],
    ) -> None:
        value, size = hash_directory(root, limits=self._limits)
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
        extension = ".idmc" if adapter.adapter_id == IDMC_ADAPTER_ID else f".{adapter.platform}"
        candidates.append(
            self._candidate(
                source_path=str(root),
                display_path=root.name,
                extension=extension,
                size_bytes=size,
                sha256=value,
                builtin_adapter_id=adapter.adapter_id,
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
            if safe_path.suffix.casefold() in self._adapter_archive_extensions and not chain:
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
            if (
                extension not in SUPPORTED_EXTENSIONS and not claimed
            ) or extension in self._adapter_archive_extensions:
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


def _looks_like_idmc_package(package: zipfile.ZipFile) -> bool:
    names = {
        PurePosixPath(entry.filename.replace("\\", "/")).as_posix().rstrip("/")
        for entry in package.infolist()
    }
    return "manifest.json" in names and any(
        name.startswith("Explore/") for name in names
    )


def _hash_stream(stream: IO[bytes]) -> str:
    digest = hashlib.sha256()
    with stream:
        while chunk := stream.read(1024 * 1024):
            digest.update(chunk)
    return digest.hexdigest()


__all__ = [
    "DiscoveryService",
    "InputRejectedError",
    "hash_directory",
    "hash_idmc_directory",
    "validate_archive_entries",
    "validate_member_path",
]
