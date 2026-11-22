"""Deterministic target-platform provider registration and discovery."""

from __future__ import annotations

from collections.abc import Iterable
from importlib.metadata import entry_points

from etl_migration_core.contracts.ir import EtlAsset, EtlPackage
from etl_migration_core.contracts.spi import (
    TargetEvaluation,
    TargetPlatformInfo,
    TargetPlatformProvider,
    UnsupportedTargetCapabilityError,
)

TARGET_ENTRY_POINT_GROUP = "etl_migration.targets"


class UnknownTargetPlatformError(KeyError):
    """Raised when a requested target platform ID is not registered."""


def _validated_info(provider: TargetPlatformProvider) -> TargetPlatformInfo:
    info = provider.info()
    if (
        info.platform_id.strip().casefold() != provider.platform_id.strip().casefold()
        or info.provider_version != provider.provider_version
        or info.supported_ir_versions != provider.supported_ir_versions
        or info.implemented != provider.implemented
        or info.capabilities != provider.capabilities
        or info.status != ("ready" if provider.implemented else "placeholder")
    ):
        raise ValueError(f"Target provider '{provider.platform_id}' returned inconsistent metadata")
    return info


class TargetPlatformRegistry:
    """Register and resolve pluggable target-platform providers."""

    def __init__(self, providers: Iterable[TargetPlatformProvider] = ()) -> None:
        self._providers: dict[str, TargetPlatformProvider] = {}
        for provider in providers:
            self.register(provider)

    @property
    def providers(self) -> tuple[TargetPlatformProvider, ...]:
        """Return registered providers in deterministic platform_id order."""
        return tuple(self._providers[key] for key in sorted(self._providers))

    def register(
        self,
        provider: TargetPlatformProvider,
        *,
        replace_placeholder: bool = False,
    ) -> None:
        """Register one unique target platform provider."""
        platform_id = provider.platform_id.strip().casefold()
        if not platform_id:
            raise ValueError("target platform_id is required")
        existing = self._providers.get(platform_id)
        if existing is not None:
            if replace_placeholder and not existing.implemented:
                self._providers[platform_id] = provider
                return
            raise ValueError(f"duplicate target platform provider: {platform_id}")
        self._providers[platform_id] = provider

    def load_entry_points(self, group: str = TARGET_ENTRY_POINT_GROUP) -> int:
        """Discover installed target provider plugins via importlib.metadata."""
        loaded = 0
        discovered: set[str] = set()
        for ep in sorted(entry_points(group=group), key=lambda item: item.name):
            factory = ep.load()
            provider = factory() if callable(factory) else factory
            key = provider.platform_id.strip().casefold()
            if key in discovered:
                raise ValueError(f"duplicate target platform entry point: {key}")
            discovered.add(key)
            existing = self._providers.get(key)
            if existing is not None and existing.implemented:
                if type(existing) is type(provider) and existing.info() == provider.info():
                    continue
                raise ValueError(f"duplicate target platform provider: {key}")
            self.register(provider, replace_placeholder=True)
            loaded += 1
        return loaded

    def get(self, platform_id: str) -> TargetPlatformProvider:
        """Return a registered provider regardless of implementation status."""
        key = platform_id.strip().casefold()
        provider = self._providers.get(key)
        if provider is None:
            raise UnknownTargetPlatformError(f"Unknown target platform: {platform_id}")
        return provider

    def require_implemented(
        self,
        platform_id: str,
        *,
        capability: str | None = None,
    ) -> TargetPlatformProvider:
        """Return an implemented provider or fail closed for placeholders."""
        provider = self.get(platform_id)
        _validated_info(provider)
        if not provider.implemented:
            raise UnsupportedTargetCapabilityError(
                provider.platform_id,
                f"Target platform '{provider.platform_id}' ({provider.display_name}) "
                "is registered as a roadmap placeholder and is not yet implemented.",
            )
        if capability is not None and capability not in provider.capabilities:
            raise UnsupportedTargetCapabilityError(
                provider.platform_id,
                f"Target platform '{provider.platform_id}' does not support "
                f"capability '{capability}'.",
            )
        return provider

    def get_info(self, platform_id: str) -> TargetPlatformInfo:
        """Return validated capability metadata for one target platform."""
        return _validated_info(self.get(platform_id))

    def evaluate_asset(
        self,
        platform_id: str,
        package: EtlPackage,
        asset: EtlAsset,
        *,
        base_reason: str,
    ) -> TargetEvaluation:
        """Evaluate a canonical asset after checking capability and IR compatibility."""
        provider = self.require_implemented(platform_id, capability="evaluate")
        if package.ir_version not in provider.supported_ir_versions:
            raise ValueError(
                f"Target platform '{provider.platform_id}' does not support "
                f"IR version {package.ir_version!r}"
            )
        if asset not in package.assets:
            raise ValueError("Asset does not belong to the supplied ETL package")
        evaluator = provider.evaluator()
        if evaluator is None:
            raise UnsupportedTargetCapabilityError(
                provider.platform_id,
                f"Target platform '{provider.platform_id}' advertises evaluation "
                "but does not provide an evaluator.",
            )
        evaluation = evaluator.evaluate_asset(package, asset, base_reason=base_reason)
        if evaluation.platform_id.strip().casefold() != provider.platform_id.strip().casefold():
            raise ValueError("Target evaluator returned a different platform identity")
        return evaluation

    def list_providers(self) -> tuple[TargetPlatformInfo, ...]:
        """Return serializable capability metadata for every registered target."""
        return tuple(_validated_info(provider) for provider in self.providers)
