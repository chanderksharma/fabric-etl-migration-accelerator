"""Core immutable domain models."""

from __future__ import annotations

from dataclasses import dataclass
from enum import StrEnum
from pathlib import Path

from etl_migration_core.ir import SourcePlatform

SUPPORTED_EXTENSIONS = frozenset({".xml", ".yxmd", ".yxmc", ".yxwz", ".yxzp"})


class InputKind(StrEnum):
    """Supported input container types."""

    FILE = "file"
    FOLDER = "folder"
    ZIP = "zip"


class SkipReason(StrEnum):
    """Stable reason codes for skipped or rejected content."""

    UNSUPPORTED_EXTENSION = "unsupported_extension"
    SYMBOLIC_LINK = "symbolic_link"
    DUPLICATE_CONTENT = "duplicate_content"
    FILE_TOO_LARGE = "file_too_large"
    ARCHIVE_ENTRY_LIMIT = "archive_entry_limit"
    ARCHIVE_SIZE_LIMIT = "archive_size_limit"
    ARCHIVE_RATIO_LIMIT = "archive_ratio_limit"
    ARCHIVE_PATH_TRAVERSAL = "archive_path_traversal"
    INVALID_ARCHIVE = "invalid_archive"
    MISSING_PATH = "missing_path"
    UNSUPPORTED_INPUT = "unsupported_input"
    UNREADABLE_INPUT = "unreadable_input"


@dataclass(frozen=True, slots=True)
class DiscoveryLimits:
    """Hard limits applied at the untrusted input boundary."""

    max_file_bytes: int = 100 * 1024 * 1024
    max_archive_entries: int = 10_000
    max_archive_uncompressed_bytes: int = 2 * 1024 * 1024 * 1024
    max_compression_ratio: float = 100.0


@dataclass(frozen=True, slots=True)
class WorkflowCandidate:
    """A unique supported workflow available for downstream parsing."""

    source_path: str
    display_path: str
    extension: str
    size_bytes: int
    sha256: str
    archive_path: str | None = None
    archive_chain: tuple[str, ...] = ()
    source_platform: SourcePlatform = SourcePlatform.ALTERYX
    source_product: str = "Alteryx Designer"
    asset_type: str = "workflow"
    adapter_id: str = "alteryx"
    adapter_version: str = "1.0.0"


@dataclass(frozen=True, slots=True)
class SkippedItem:
    """An input that was not accepted for processing."""

    path: str
    reason: SkipReason
    detail: str


@dataclass(frozen=True, slots=True)
class DiscoverySummary:
    """Pre-run summary shown before processing begins."""

    input_path: str
    input_kind: InputKind
    workflows: tuple[WorkflowCandidate, ...]
    skipped: tuple[SkippedItem, ...]
    total_size_bytes: int

    @property
    def workflow_count(self) -> int:
        """Return the number of unique workflows."""
        return len(self.workflows)

    @property
    def skipped_count(self) -> int:
        """Return the number of skipped items."""
        return len(self.skipped)


def classify_input(path: Path) -> InputKind:
    """Classify a local input path.

    Raises:
        ValueError: If the path is missing or is not a supported container.
    """
    if not path.exists():
        raise ValueError(f"Input path does not exist: {path}")
    if path.is_symlink():
        raise ValueError(f"Symbolic links are not accepted: {path}")
    if path.is_dir():
        return InputKind.FOLDER
    if path.is_file() and path.suffix.casefold() == ".zip":
        return InputKind.ZIP
    if path.is_file():
        return InputKind.FILE
    raise ValueError(f"Unsupported input path: {path}")
