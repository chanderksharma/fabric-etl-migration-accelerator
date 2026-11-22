"""Default target platform registry combining Fabric and roadmap placeholders."""

from __future__ import annotations

from collections.abc import Collection

from etl_migration_core.plugins import PluginErrorMode, effective_plugin_allowlist
from etl_migration_core.targets import (
    TargetPlatformRegistry,
    builtin_placeholder_providers,
)
from etl_target_fabric.provider import FabricTargetProvider


def create_default_target_registry(
    *,
    load_entry_points: bool = True,
    plugin_errors: PluginErrorMode = "record",
    plugin_allowlist: Collection[str] | None = None,
) -> TargetPlatformRegistry:
    """Build the target registry with Microsoft Fabric and roadmap placeholders.

    A broken installed plugin is recorded in ``plugin_results`` instead of preventing
    the built-in providers from loading. ``plugin_allowlist=None`` applies the
    ``ACCELERATOR_PLUGIN_ALLOWLIST`` policy (every installed plugin when it is unset).
    """
    registry = TargetPlatformRegistry(
        (
            FabricTargetProvider(),
            *builtin_placeholder_providers(),
        )
    )
    if load_entry_points:
        registry.load_entry_points(
            allowlist=effective_plugin_allowlist(plugin_allowlist), on_error=plugin_errors
        )
    return registry
