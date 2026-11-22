"""Typed, read-only view over installed source adapters and target providers."""

from __future__ import annotations

from collections.abc import Collection

from pydantic import BaseModel, ConfigDict

from etl_migration_core.contracts.spi import Diagnostic, TargetPlatformInfo
from etl_migration_core.plugins import PluginLoadResult
from etl_migration_core.sources.base import SourceFileDiscoveryAdapter, SourceStreamProbeAdapter
from etl_migration_core.sources.registry import SourceAdapterRegistry
from etl_migration_core.targets.registry import TargetCatalog, TargetPlatformRegistry

_MAX_MESSAGE_CHARS = 2000


class SourceDescriptor(BaseModel):
    """Public identity, version, and discovery metadata for one source adapter."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    adapter_id: str
    platform: str
    product: str
    origin: str
    adapter_version: str
    parser_version: str
    registry_version: str
    rules_version: str
    supported_extensions: tuple[str, ...] = ()
    stream_probe: bool = False


class TargetDescriptor(TargetPlatformInfo):
    """Validated target metadata together with where the provider came from."""

    origin: str = "builtin"


class PluginCatalog(BaseModel):
    """Everything an operator needs to see which plugins are active and which are not."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    allowlist: tuple[str, ...] | None = None
    sources: tuple[SourceDescriptor, ...]
    targets: tuple[TargetDescriptor, ...]
    plugins: tuple[PluginLoadResult, ...]
    diagnostics: tuple[Diagnostic, ...]
    failed_count: int


class PluginHost:
    """Single access point for the installed source adapters and target providers."""

    def __init__(
        self,
        sources: SourceAdapterRegistry | None = None,
        targets: TargetPlatformRegistry | None = None,
        *,
        allowlist: Collection[str] | None = None,
    ) -> None:
        self._sources = SourceAdapterRegistry() if sources is None else sources
        self._targets = TargetPlatformRegistry() if targets is None else targets
        self._allowlist = tuple(sorted(allowlist)) if allowlist is not None else None

    def sources(self) -> tuple[SourceDescriptor, ...]:
        """Describe every registered source adapter in stable identity order."""
        return tuple(
            SourceDescriptor(
                adapter_id=adapter.adapter_id,
                platform=str(adapter.platform),
                product=adapter.product,
                origin=self._sources.origin_of(adapter.adapter_id),
                adapter_version=adapter.adapter_version,
                parser_version=adapter.parser_version,
                registry_version=adapter.registry_version,
                rules_version=adapter.rules_version,
                supported_extensions=(
                    tuple(adapter.supported_extensions)
                    if isinstance(adapter, SourceFileDiscoveryAdapter)
                    else ()
                ),
                stream_probe=isinstance(adapter, SourceStreamProbeAdapter),
            )
            for adapter in self._sources.adapters
        )

    def target_catalog(self) -> TargetCatalog:
        """Validated provider metadata plus the providers excluded for inconsistent metadata."""
        return self._targets.catalog()

    def targets(self) -> tuple[TargetDescriptor, ...]:
        """Describe every valid target provider in stable platform order."""
        return tuple(
            TargetDescriptor(
                **info.model_dump(), origin=self._targets.origin_of(info.platform_id)
            )
            for info in self.target_catalog().targets
        )

    def plugin_results(self) -> tuple[PluginLoadResult, ...]:
        """Per-entry-point outcomes from both registries."""
        return (*self._sources.plugin_results, *self._targets.plugin_results)

    def diagnostics(self) -> tuple[Diagnostic, ...]:
        """Structured findings for failed plugins, skipped plugins, and invalid providers."""
        findings: list[Diagnostic] = []
        for result in self.plugin_results():
            subject = f"{result.group}/{result.name}"
            if result.status == "failed":
                findings.append(
                    Diagnostic(
                        code="PLUGIN_LOAD_FAILED",
                        severity="error",
                        stage="plugin",
                        message=f"{subject}: {result.detail or 'failed to load'}"[
                            :_MAX_MESSAGE_CHARS
                        ],
                        remediation=(
                            "Fix or uninstall the plugin distribution, or remove it from the "
                            "plugin allowlist."
                        ),
                    )
                )
            elif result.status == "skipped":
                findings.append(
                    Diagnostic(
                        code="PLUGIN_SKIPPED",
                        severity="info",
                        stage="plugin",
                        message=f"{subject} was not loaded: {result.detail}"[:_MAX_MESSAGE_CHARS],
                    )
                )
        findings.extend(
            Diagnostic(
                code="TARGET_PROVIDER_INVALID",
                severity="error",
                stage="plugin",
                message=f"{fault.platform_id}: {fault.detail}"[:_MAX_MESSAGE_CHARS],
                remediation="Make the provider's info() match its declared properties.",
            )
            for fault in self.target_catalog().faults
        )
        return tuple(findings)

    def catalog(self) -> PluginCatalog:
        """Return one consistent snapshot of sources, targets, load results, and findings."""
        results = self.plugin_results()
        return PluginCatalog(
            allowlist=self._allowlist,
            sources=self.sources(),
            targets=self.targets(),
            plugins=results,
            diagnostics=self.diagnostics(),
            failed_count=sum(result.status == "failed" for result in results),
        )
