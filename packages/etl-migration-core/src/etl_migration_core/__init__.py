"""Core canonical ETL IR, discovery, source adapters, and plugin SPI."""

from etl_migration_core.contracts.ir import (
    EXTENSIBLE_SOURCE_IR_VERSION,
    IR_VERSION,
    EtlAsset,
    EtlGraph,
    EtlPackage,
    SourcePlatform,
    SourcePlatformId,
)
from etl_migration_core.contracts.spi import (
    IR_SPI_VERSION,
    TargetEvaluation,
    TargetPlatformInfo,
    TargetPlatformProvider,
    UnsupportedTargetCapabilityError,
)

__version__ = "1.0.0"

__all__ = [
    "EXTENSIBLE_SOURCE_IR_VERSION",
    "IR_SPI_VERSION",
    "IR_VERSION",
    "EtlAsset",
    "EtlGraph",
    "EtlPackage",
    "SourcePlatform",
    "SourcePlatformId",
    "TargetEvaluation",
    "TargetPlatformInfo",
    "TargetPlatformProvider",
    "UnsupportedTargetCapabilityError",
    "__version__",
]
