"""Default target platform registry combining Fabric and roadmap placeholders."""

from __future__ import annotations

from etl_migration_core.targets import (
    TargetPlatformRegistry,
    builtin_placeholder_providers,
)
from etl_target_fabric.provider import FabricTargetProvider


def create_default_target_registry(
    *, load_entry_points: bool = True
) -> TargetPlatformRegistry:
    """Build the target registry with Microsoft Fabric and roadmap placeholders."""
    registry = TargetPlatformRegistry(
        (
            FabricTargetProvider(),
            *builtin_placeholder_providers(),
        )
    )
    if load_entry_points:
        registry.load_entry_points()
    return registry
