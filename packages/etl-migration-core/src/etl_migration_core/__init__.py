"""Core canonical ETL IR, discovery, source adapters, and plugin SPI."""

from etl_migration_core.ir import IR_VERSION, EtlAsset, EtlGraph, EtlPackage, SourcePlatform
from etl_migration_core.spi import (
    IR_SPI_VERSION,
    TargetEvaluation,
    TargetPlatformInfo,
    TargetPlatformProvider,
    UnsupportedTargetCapabilityError,
)

__version__ = "1.0.0"

__all__ = [
    "IR_SPI_VERSION",
    "IR_VERSION",
    "EtlAsset",
    "EtlGraph",
    "EtlPackage",
    "SourcePlatform",
    "TargetEvaluation",
    "TargetPlatformInfo",
    "TargetPlatformProvider",
    "UnsupportedTargetCapabilityError",
    "__version__",
]
