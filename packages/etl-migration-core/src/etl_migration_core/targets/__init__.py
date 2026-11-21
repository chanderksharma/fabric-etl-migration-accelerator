"""Pluggable target platform registry and fail-closed roadmap placeholders."""

from etl_migration_core.targets.placeholders import (
    PlaceholderTargetProvider,
    builtin_placeholder_providers,
)
from etl_migration_core.targets.registry import (
    TARGET_ENTRY_POINT_GROUP,
    TargetPlatformRegistry,
    UnknownTargetPlatformError,
)


def create_target_registry(*, load_entry_points: bool = True) -> TargetPlatformRegistry:
    """Create a target registry seeded with roadmap placeholders and installed plugins."""
    registry = TargetPlatformRegistry(builtin_placeholder_providers())
    if load_entry_points:
        registry.load_entry_points()
    return registry


__all__ = [
    "TARGET_ENTRY_POINT_GROUP",
    "PlaceholderTargetProvider",
    "TargetPlatformRegistry",
    "UnknownTargetPlatformError",
    "builtin_placeholder_providers",
    "create_target_registry",
]
