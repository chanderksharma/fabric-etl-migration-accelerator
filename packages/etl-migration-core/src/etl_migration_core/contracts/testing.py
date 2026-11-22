"""Reusable conformance checks for SourceAdapter and TargetPlatformProvider plugins."""

from __future__ import annotations

from pathlib import Path

from etl_migration_core.contracts.ir import EtlPackage
from etl_migration_core.contracts.spi import (
    TargetCapacityProvider,
    TargetCodeGeneratorProvider,
    TargetPlatformProvider,
)
from etl_migration_core.sources.base import (
    SourceAdapter,
    SourceFileDiscoveryAdapter,
    SourceStreamProbeAdapter,
)
from etl_migration_core.sources.registry import SourceAdapterRegistry
from etl_migration_core.targets.registry import TargetPlatformRegistry


def assert_source_adapter_conformance(
    adapter: SourceAdapter,
    sample_path: Path,
    display_path: str | None = None,
) -> EtlPackage:
    """Validate SourceAdapter metadata, probing, stream probing, and deterministic IR parsing."""
    for field_name in (
        "adapter_id",
        "product",
        "adapter_version",
        "parser_version",
        "registry_version",
        "rules_version",
    ):
        value = getattr(adapter, field_name)
        if not isinstance(value, str) or not value.strip():
            raise AssertionError(f"SourceAdapter.{field_name} must be a non-empty string")
    effective_display = display_path or sample_path.name
    registry = SourceAdapterRegistry((adapter,))
    if isinstance(adapter, SourceFileDiscoveryAdapter):
        registry.file_extensions()
    detected = registry.detect(sample_path, effective_display)
    if isinstance(adapter, SourceStreamProbeAdapter) and sample_path.is_file():
        stream_detected = registry.detect_bytes(
            sample_path.read_bytes(), effective_display
        )
        if stream_detected.match != detected.match:
            raise AssertionError("probe_bytes must match probe for identical file input")
    first = registry.parse(sample_path, detected.match)
    second = registry.parse(sample_path, detected.match)
    if first.model_dump() != second.model_dump():
        raise AssertionError("SourceAdapter.parse must be deterministic across repeated runs")
    return first


def assert_target_provider_conformance(
    provider: TargetPlatformProvider,
    package: EtlPackage,
) -> None:
    """Validate TargetPlatformProvider metadata consistency, capability gates, and IR checks."""
    registry = TargetPlatformRegistry((provider,))
    info = registry.get_info(provider.platform_id)
    if info.implemented and "evaluate" in info.capabilities and package.assets:
        evaluation = registry.evaluate_asset(
            provider.platform_id,
            package,
            package.assets[0],
            base_reason="Conformance check",
        )
        if evaluation.platform_id.casefold() != provider.platform_id.casefold():
            raise AssertionError("Target evaluator platform_id mismatch")
    if info.implemented and "codegen" in info.capabilities:
        if not isinstance(provider, TargetCodeGeneratorProvider):
            raise AssertionError("codegen capability requires TargetCodeGeneratorProvider")
        generator = provider.code_generator()
        if generator is None or not generator.supported_target_kinds:
            raise AssertionError("codegen provider must expose supported_target_kinds")
    if info.implemented and "capacity" in info.capabilities:
        if not isinstance(provider, TargetCapacityProvider):
            raise AssertionError("capacity capability requires TargetCapacityProvider")
        estimator = provider.capacity_estimator()
        if estimator is None:
            raise AssertionError("capacity provider must return a capacity estimator")
    future = package.model_copy(update={"ir_version": "99.0.0"})
    if future.assets and info.implemented and "evaluate" in info.capabilities:
        try:
            registry.evaluate_asset(
                provider.platform_id,
                future,
                future.assets[0],
                base_reason="Incompatible IR check",
            )
        except ValueError:
            pass
        else:
            raise AssertionError("Target provider must reject unsupported IR version '99.0.0'")
