"""Source platform adapters for ETL metadata."""

from accelerator.sources.base import SourceAdapter, SourceMatch
from accelerator.sources.registry import (
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
    "SourceMatch",
    "UnknownSourceFormatError",
]
