"""Pluggable target platform registry and fail-closed roadmap placeholders."""

from collections.abc import Collection

from etl_migration_core.plugins import PluginErrorMode, effective_plugin_allowlist
from etl_migration_core.targets.placeholders import (
    PlaceholderTargetProvider,
    builtin_placeholder_providers,
)
from etl_migration_core.targets.registry import (
    TARGET_ENTRY_POINT_GROUP,
    TargetCatalog,
    TargetPlatformRegistry,
    TargetProviderFault,
    TargetProviderFaultError,
    UnknownTargetPlatformError,
)


def create_target_registry(
    *,
    load_entry_points: bool = True,
    plugin_errors: PluginErrorMode = "record",
    plugin_allowlist: Collection[str] | None = None,
) -> TargetPlatformRegistry:
    """Create a target registry seeded with roadmap placeholders and installed plugins.

    ``plugin_allowlist=None`` applies the ``ACCELERATOR_PLUGIN_ALLOWLIST`` policy (every
    installed plugin when it is unset); pass a collection to override it.
    """
    registry = TargetPlatformRegistry(builtin_placeholder_providers())
    if load_entry_points:
        registry.load_entry_points(
            allowlist=effective_plugin_allowlist(plugin_allowlist), on_error=plugin_errors
        )
    return registry


__all__ = [
    "TARGET_ENTRY_POINT_GROUP",
    "PlaceholderTargetProvider",
    "TargetCatalog",
    "TargetPlatformRegistry",
    "TargetProviderFault",
    "TargetProviderFaultError",
    "UnknownTargetPlatformError",
    "builtin_placeholder_providers",
    "create_target_registry",
]
