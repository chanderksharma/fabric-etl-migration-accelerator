"""Secure input discovery, archive validation, and domain models."""

from etl_migration_core.intake.archive import (
    InputRejectedError,
    hash_directory,
    hash_idmc_directory,
    validate_archive_entries,
    validate_member_path,
)
from etl_migration_core.intake.discovery import DiscoveryService
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
from etl_migration_core.intake.schemas import (
    DiscoverySummaryResponse,
    SkippedItemResponse,
    WorkflowCandidateResponse,
)

__all__ = [
    "SUPPORTED_EXTENSIONS",
    "DiscoveryLimits",
    "DiscoveryService",
    "DiscoverySummary",
    "DiscoverySummaryResponse",
    "InputKind",
    "InputRejectedError",
    "SkipReason",
    "SkippedItem",
    "SkippedItemResponse",
    "WorkflowCandidate",
    "WorkflowCandidateResponse",
    "classify_input",
    "hash_directory",
    "hash_idmc_directory",
    "validate_archive_entries",
    "validate_member_path",
]
