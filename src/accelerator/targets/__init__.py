"""Target platform registry wiring for the accelerator app shell."""

from accelerator.targets.defaults import create_default_target_registry
from etl_migration_core.targets import (
    PlaceholderTargetProvider,
    TargetPlatformRegistry,
    UnknownTargetPlatformError,
    builtin_placeholder_providers,
)
from etl_target_fabric.provider import FabricTargetEvaluator, FabricTargetProvider

__all__ = [
    "FabricTargetEvaluator",
    "FabricTargetProvider",
    "PlaceholderTargetProvider",
    "TargetPlatformRegistry",
    "UnknownTargetPlatformError",
    "builtin_placeholder_providers",
    "create_default_target_registry",
]
