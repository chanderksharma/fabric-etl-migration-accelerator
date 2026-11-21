"""Microsoft Fabric target-platform provider, compilers, and capacity model."""

from etl_target_fabric.provider import FabricTargetEvaluator, FabricTargetProvider

__version__ = "1.0.0"

__all__ = [
    "FabricTargetEvaluator",
    "FabricTargetProvider",
    "__version__",
]
