"""Contracts implemented by source-specific ETL adapters."""

from __future__ import annotations

from pathlib import Path
from typing import Protocol

from pydantic import BaseModel, ConfigDict, Field

from etl_migration_core.ir import EtlPackage, SourcePlatform


class SourceMatch(BaseModel):
    """Bounded adapter detection result for one staged source item."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    adapter_id: str = Field(min_length=1, max_length=128)
    platform: SourcePlatform
    product: str = Field(min_length=1, max_length=256)
    asset_type: str = Field(min_length=1, max_length=128)
    confidence: int = Field(ge=1, le=100)
    display_path: str = Field(min_length=1, max_length=4096)
    product_version: str | None = Field(default=None, max_length=128)


class SourceAdapter(Protocol):
    """Source adapter interface used by discovery and run orchestration."""

    @property
    def adapter_id(self) -> str:
        """Return the stable adapter identity."""

    @property
    def platform(self) -> SourcePlatform:
        """Return the normalized source platform."""

    @property
    def product(self) -> str:
        """Return the source product display name."""

    @property
    def adapter_version(self) -> str:
        """Return the adapter contract version."""

    @property
    def parser_version(self) -> str:
        """Return the native parser version."""

    @property
    def registry_version(self) -> str:
        """Return the platform support registry version."""

    @property
    def rules_version(self) -> str:
        """Return the platform assessment rules version."""

    def probe(self, path: Path, display_path: str) -> SourceMatch | None:
        """Return a confidence-ranked match without executing source content."""

    def parse(self, path: Path, match: SourceMatch) -> EtlPackage:
        """Parse one staged source item into the canonical ETL IR."""
