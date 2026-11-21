"""Default target platform registry combining Fabric and roadmap placeholders."""

from __future__ import annotations

from accelerator.targets.fabric import FabricTargetProvider
from accelerator.targets.placeholders import builtin_placeholder_providers
from accelerator.targets.registry import TargetPlatformRegistry


def create_default_target_registry(*, load_entry_points: bool = True) -> TargetPlatformRegistry:
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
