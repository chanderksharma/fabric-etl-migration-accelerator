"""Deterministic source adapter registration and dispatch."""

from __future__ import annotations

from collections.abc import Iterable
from dataclasses import dataclass
from importlib.metadata import entry_points
from pathlib import Path

from etl_migration_core.contracts.ir import EtlPackage
from etl_migration_core.sources.base import SourceAdapter, SourceMatch

SOURCE_ENTRY_POINT_GROUP = "etl_migration.sources"


class UnknownSourceFormatError(ValueError):
    """No registered adapter recognized the staged source."""


class AmbiguousSourceFormatError(ValueError):
    """Multiple adapters reported the same highest detection confidence."""


@dataclass(frozen=True, slots=True)
class DetectedSource:
    """Selected adapter and its immutable detection result."""

    adapter: SourceAdapter
    match: SourceMatch


class SourceAdapterRegistry:
    """Register adapters and select one using deterministic confidence ranking."""

    def __init__(self, adapters: Iterable[SourceAdapter] = ()) -> None:
        self._adapters: dict[str, SourceAdapter] = {}
        for adapter in adapters:
            self.register(adapter)

    @property
    def adapters(self) -> tuple[SourceAdapter, ...]:
        """Return adapters ordered by stable adapter identity."""
        return tuple(self._adapters[key] for key in sorted(self._adapters))

    def register(self, adapter: SourceAdapter) -> None:
        """Register one unique source adapter."""
        identity = adapter.adapter_id.strip()
        if not identity:
            raise ValueError("source adapter identity is required")
        if identity in self._adapters:
            raise ValueError(f"duplicate source adapter identity: {identity}")
        self._adapters[identity] = adapter

    def load_entry_points(self, group: str = SOURCE_ENTRY_POINT_GROUP) -> int:
        """Discover external source adapter plugins via importlib.metadata."""
        loaded = 0
        for ep in sorted(entry_points(group=group), key=lambda item: item.name):
            factory = ep.load()
            adapter = factory() if callable(factory) else factory
            if adapter.adapter_id not in self._adapters:
                self.register(adapter)
                loaded += 1
        return loaded

    def detect(self, path: Path, display_path: str) -> DetectedSource:
        """Select the single highest-confidence adapter for a staged source."""
        matches = [
            (adapter, match)
            for adapter in self.adapters
            if (match := adapter.probe(path, display_path)) is not None
        ]
        if not matches:
            raise UnknownSourceFormatError(
                f"No source adapter recognized {display_path}"
            )
        matches.sort(key=lambda item: (-item[1].confidence, item[0].adapter_id))
        confidence = matches[0][1].confidence
        strongest = [item for item in matches if item[1].confidence == confidence]
        if len(strongest) > 1:
            identities = ", ".join(item[0].adapter_id for item in strongest)
            raise AmbiguousSourceFormatError(
                f"Ambiguous source format for {display_path}: {identities}"
            )
        adapter, match = strongest[0]
        return DetectedSource(adapter=adapter, match=match)

    def parse(self, path: Path, match: SourceMatch) -> EtlPackage:
        """Dispatch parsing to the adapter named by a prior detection result."""
        adapter = self._adapters.get(match.adapter_id)
        if adapter is None:
            raise UnknownSourceFormatError(
                f"Source adapter is not registered: {match.adapter_id}"
            )
        if adapter.platform is not match.platform:
            raise ValueError("source adapter platform changed after detection")
        return adapter.parse(path, match)

