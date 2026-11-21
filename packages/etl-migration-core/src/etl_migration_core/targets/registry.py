"""Deterministic target-platform provider registration and discovery."""

from __future__ import annotations

from collections.abc import Iterable
from importlib.metadata import entry_points

from etl_migration_core.contracts.spi import (
    TargetPlatformInfo,
    TargetPlatformProvider,
    UnsupportedTargetCapabilityError,
)

TARGET_ENTRY_POINT_GROUP = "etl_migration.targets"


class UnknownTargetPlatformError(KeyError):
    """Raised when a requested target platform ID is not registered."""


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
        for ep in sorted(entry_points(group=group), key=lambda item: item.name):
            factory = ep.load()
            provider = factory() if callable(factory) else factory
            key = provider.platform_id.strip().casefold()
            existing = self._providers.get(key)
            if existing is not None and existing.implemented:
                continue
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

    def list_providers(self) -> tuple[TargetPlatformInfo, ...]:
        """Return serializable capability metadata for every registered target."""
        return tuple(provider.info() for provider in self.providers)
