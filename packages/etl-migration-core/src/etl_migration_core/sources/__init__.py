"""Source platform adapters for ETL metadata."""

from etl_migration_core.sources.base import SourceAdapter, SourceFileDiscoveryAdapter, SourceMatch
from etl_migration_core.sources.io import SourceChangedError, SourceTooLargeError, read_bounded
from etl_migration_core.sources.registry import (
    AmbiguousSourceFormatError,
    DetectedSource,
    SourceAdapterFaultError,
    SourceAdapterRegistry,
    UnknownSourceFormatError,
)

__all__ = [
    "AmbiguousSourceFormatError",
    "DetectedSource",
    "SourceAdapter",
    "SourceAdapterFaultError",
    "SourceAdapterRegistry",
    "SourceChangedError",
    "SourceFileDiscoveryAdapter",
    "SourceMatch",
    "SourceTooLargeError",
    "UnknownSourceFormatError",
    "read_bounded",
]
