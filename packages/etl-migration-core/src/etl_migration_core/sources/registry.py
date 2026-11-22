"""Deterministic source adapter registration and dispatch."""

from __future__ import annotations

import re
from collections.abc import Collection, Iterable, Iterator, Sequence
from contextlib import contextmanager
from dataclasses import dataclass
from importlib.metadata import entry_points
from pathlib import Path
from typing import Literal

from etl_migration_core.contracts.ir import EtlPackage
from etl_migration_core.plugins import (
    EntryPointProvenance,
    PluginErrorMode,
    PluginLoadResult,
    fault_detail,
)
from etl_migration_core.sources.base import (
    SourceAdapter,
    SourceFileDiscoveryAdapter,
    SourceMatch,
    SourceStreamProbeAdapter,
)

SOURCE_ENTRY_POINT_GROUP = "etl_migration.sources"
BUILTIN_ORIGIN = "builtin"
_EXTENSION_PATTERN = re.compile(r"\.[a-z0-9][a-z0-9_-]{0,15}")
_STRING_ATTRIBUTES = (
    "adapter_id",
    "platform",
    "product",
    "adapter_version",
    "parser_version",
    "registry_version",
    "rules_version",
)


class UnknownSourceFormatError(ValueError):
    """No registered adapter recognized the staged source."""


class AmbiguousSourceFormatError(ValueError):
    """Multiple adapters reported the same highest detection confidence."""


class SourceAdapterFaultError(ValueError):
    """A source adapter raised an unexpected exception instead of a documented error."""

    def __init__(
        self, adapter_id: str, stage: Literal["probe", "parse"], error: BaseException
    ) -> None:
        super().__init__(
            f"Source adapter {adapter_id!r} faulted during {stage}: {fault_detail(error)}"
        )
        self.adapter_id = adapter_id
        self.stage = stage


@contextmanager
def _guard(adapter: SourceAdapter, stage: Literal["probe", "parse"]) -> Iterator[None]:
    """Contain unexpected adapter exceptions; ValueError and OSError are documented outcomes."""
    try:
        yield
    except (ValueError, OSError):
        raise
    except Exception as error:
        raise SourceAdapterFaultError(adapter.adapter_id, stage, error) from error


@dataclass(frozen=True, slots=True)
class DetectedSource:
    """Selected adapter and its immutable detection result."""

    adapter: SourceAdapter
    match: SourceMatch


class SourceAdapterRegistry:
    """Register adapters and select one using deterministic confidence ranking."""

    def __init__(self, adapters: Iterable[SourceAdapter] = ()) -> None:
        self._adapters: dict[str, SourceAdapter] = {}
        self._origins: dict[str, str] = {}
        self._plugin_results: list[PluginLoadResult] = []
        for adapter in adapters:
            self.register(adapter)

    @property
    def adapters(self) -> tuple[SourceAdapter, ...]:
        """Return adapters ordered by stable adapter identity."""
        return tuple(self._adapters[key] for key in sorted(self._adapters))

    @property
    def plugin_results(self) -> tuple[PluginLoadResult, ...]:
        """Return the outcome of every entry point considered by ``load_entry_points``."""
        return tuple(self._plugin_results)

    def origin_of(self, adapter_id: str) -> str:
        """Return ``builtin`` or ``plugin:<entry point>`` for a registered adapter."""
        return self._origins[adapter_id]

    def get(self, adapter_id: str) -> SourceAdapter | None:
        """Return one registered adapter by identity."""
        return self._adapters.get(adapter_id)

    def file_extensions(self) -> frozenset[str]:
        """Return the extensions registered adapters claim for local file discovery."""
        return frozenset(
            extension
            for adapter in self.adapters
            if isinstance(adapter, SourceFileDiscoveryAdapter)
            for extension in adapter.supported_extensions
        )

    def supports_stream_probe(self, extension: str) -> bool:
        """Return True when every adapter claiming the extension can probe bytes in memory."""
        normalized = extension.casefold()
        candidates = [
            adapter
            for adapter in self.adapters
            if isinstance(adapter, SourceFileDiscoveryAdapter)
            and normalized in adapter.supported_extensions
        ]
        return bool(candidates) and all(
            isinstance(adapter, SourceStreamProbeAdapter) for adapter in candidates
        )

    def register(self, adapter: SourceAdapter, *, origin: str = BUILTIN_ORIGIN) -> None:
        """Register one unique source adapter.

        Identity, version, and extension metadata is validated here, where plugin metadata
        enters, so one malformed plugin is rejected (and recorded by ``load_entry_points``)
        instead of failing every later discovery or the plugin catalog itself.
        """
        for attribute in _STRING_ATTRIBUTES:
            if not isinstance(getattr(adapter, attribute, None), str):
                raise ValueError(
                    f"source adapter {type(adapter).__name__} must declare {attribute} as a string"
                )
        identity = adapter.adapter_id.strip()
        if not identity:
            raise ValueError("source adapter identity is required")
        if identity in self._adapters:
            raise ValueError(f"duplicate source adapter identity: {identity}")
        if isinstance(adapter, SourceFileDiscoveryAdapter):
            for extension in adapter.supported_extensions:
                if not _EXTENSION_PATTERN.fullmatch(extension):
                    raise ValueError(f"invalid source extension: {extension!r}")
        self._adapters[identity] = adapter
        self._origins[identity] = origin

    def load_entry_points(
        self,
        group: str = SOURCE_ENTRY_POINT_GROUP,
        *,
        allowlist: Collection[str] | None = None,
        on_error: PluginErrorMode = "raise",
    ) -> int:
        """Discover external source adapter plugins via importlib.metadata.

        ``on_error="record"`` isolates a broken plugin: it is reported in
        ``plugin_results`` and every other adapter still loads. ``allowlist`` limits
        loading to the named entry points.
        """
        loaded = 0
        for ep in sorted(entry_points(group=group), key=lambda item: item.name):
            provenance = EntryPointProvenance.of(ep, group)
            if allowlist is not None and ep.name not in allowlist:
                self._plugin_results.append(provenance.skipped("not in the plugin allowlist"))
                continue
            try:
                factory = ep.load()
                adapter = factory() if callable(factory) else factory
                self.register(adapter, origin=f"plugin:{ep.name}")
            except Exception as error:
                if on_error == "raise":
                    raise
                self._plugin_results.append(provenance.failed(error))
                continue
            self._plugin_results.append(provenance.loaded(adapter.adapter_id))
            loaded += 1
        return loaded

    def detect(self, path: Path, display_path: str) -> DetectedSource:
        """Select the single highest-confidence adapter for a staged source."""
        matches: list[tuple[SourceAdapter, SourceMatch]] = []
        for adapter in self.adapters:
            with _guard(adapter, "probe"):
                match = adapter.probe(path, display_path)
            if match is not None:
                matches.append((adapter, match))
        return self._select_match(matches, display_path)

    def detect_bytes(self, content: bytes, display_path: str) -> DetectedSource:
        """Select the highest-confidence stream-capable adapter from raw bytes."""
        matches: list[tuple[SourceAdapter, SourceMatch]] = []
        for adapter in self.adapters:
            if not isinstance(adapter, SourceStreamProbeAdapter):
                continue
            with _guard(adapter, "probe"):
                match = adapter.probe_bytes(content, display_path)
            if match is not None:
                matches.append((adapter, match))
        return self._select_match(matches, display_path)

    @staticmethod
    def _select_match(
        matches: Sequence[tuple[SourceAdapter, SourceMatch]], display_path: str
    ) -> DetectedSource:
        if not matches:
            raise UnknownSourceFormatError(
                f"No source adapter recognized {display_path}"
            )
        ranked = sorted(
            matches, key=lambda item: (-item[1].confidence, item[0].adapter_id)
        )
        confidence = ranked[0][1].confidence
        strongest = [item for item in ranked if item[1].confidence == confidence]
        if len(strongest) > 1:
            identities = ", ".join(item[0].adapter_id for item in strongest)
            raise AmbiguousSourceFormatError(
                f"Ambiguous source format for {display_path}: {identities}"
            )
        adapter, match = strongest[0]
        if match.adapter_id != adapter.adapter_id or match.platform != adapter.platform:
            raise ValueError(
                f"source adapter {adapter.adapter_id!r} returned inconsistent identity"
            )
        return DetectedSource(adapter=adapter, match=match)

    def parse(self, path: Path, match: SourceMatch) -> EtlPackage:
        """Dispatch parsing to the adapter named by a prior detection result."""
        adapter = self._adapters.get(match.adapter_id)
        if adapter is None:
            raise UnknownSourceFormatError(
                f"Source adapter is not registered: {match.adapter_id}"
            )
        if adapter.platform != match.platform:
            raise ValueError("source adapter platform changed after detection")
        with _guard(adapter, "parse"):
            package = adapter.parse(path, match)
        if package.source_platform != match.platform:
            raise ValueError("source adapter returned a package with a different platform")
        return package

