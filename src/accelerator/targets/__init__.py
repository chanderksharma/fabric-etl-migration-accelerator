"""Pluggable target platform providers and registry."""

from accelerator.targets.defaults import create_default_target_registry
from accelerator.targets.fabric import FabricTargetEvaluator, FabricTargetProvider
from accelerator.targets.placeholders import (
    PlaceholderTargetProvider,
    builtin_placeholder_providers,
)
from accelerator.targets.registry import (
    TargetPlatformRegistry,
    UnknownTargetPlatformError,
)

__all__ = [
    "FabricTargetEvaluator",
    "FabricTargetProvider",
    "PlaceholderTargetProvider",
    "TargetPlatformRegistry",
    "UnknownTargetPlatformError",
    "builtin_placeholder_providers",
    "create_default_target_registry",
]
