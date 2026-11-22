"""Source platform adapters for ETL metadata."""

from etl_migration_core.sources.base import SourceAdapter, SourceFileDiscoveryAdapter, SourceMatch
from etl_migration_core.sources.registry import (
    AmbiguousSourceFormatError,
    DetectedSource,
    SourceAdapterRegistry,
    UnknownSourceFormatError,
)

__all__ = [
    "AmbiguousSourceFormatError",
    "DetectedSource",
    "SourceAdapter",
    "SourceAdapterRegistry",
    "SourceFileDiscoveryAdapter",
    "SourceMatch",
    "UnknownSourceFormatError",
]
