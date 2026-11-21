"""Compatibility re-export of canonical IR-to-Fabric compiler from etl-target-fabric."""

from __future__ import annotations

from accelerator.etl_assessment import EtlAssessment
from etl_migration_core.ir import EtlAsset, EtlPackage
from etl_target_fabric.etl_generation import (
    ETL_COMPILER_VERSION as ETL_COMPILER_VERSION,
)
from etl_target_fabric.etl_generation import (
    SUPPORTED_MAPPING_OPERATIONS as SUPPORTED_MAPPING_OPERATIONS,
)
from etl_target_fabric.etl_generation import (
    CompilationTarget as CompilationTarget,
)
from etl_target_fabric.etl_generation import (
    EtlCompiledCandidate as EtlCompiledCandidate,
)
from etl_target_fabric.etl_generation import (
    EtlCompiledTargets as EtlCompiledTargets,
)
from etl_target_fabric.etl_generation import (
    compile_asset as compile_asset,
)
from etl_target_fabric.etl_generation import (
    compile_asset_targets as compile_asset_targets,
)


def apply_native_route(
    package: EtlPackage,
    asset: EtlAsset,
    assessment: EtlAssessment,
) -> EtlAssessment:
    """Compatibility wrapper applying Fabric target routing onto EtlAssessment."""
    from accelerator.etl_routing import apply_native_route as route_asset

    return route_asset(package, asset, assessment)
