"""Serializable assessment responses built from static, compiler-free assessments."""

from typing import Any

from etl_target_fabric.assessment.ir_assessment import EtlAssessment
from etl_target_fabric.assessment.schemas import (
    ToolInventoryResponse,
    WorkflowAssessmentResponse,
)
from etl_target_fabric.capacity.model import CapacityStaticProfile


def __getattr__(name: str) -> Any:
    """Resolve the relocated application lazily so this package never imports a compiler."""
    if name == "FabricAssessmentApplication":
        from etl_target_fabric.application import FabricAssessmentApplication

        return FabricAssessmentApplication
    raise AttributeError(f"module {__name__!r} has no attribute {name!r}")


def assessment_response(
    display_path: str,
    assessment: EtlAssessment,
    *,
    capacity_profile: CapacityStaticProfile | None = None,
) -> WorkflowAssessmentResponse:
    asset_path = "/".join(
        part
        for part in (assessment.folder, assessment.name)
        if part
    )
    path = f"{display_path}!{asset_path}" if asset_path else display_path
    return WorkflowAssessmentResponse(
        path=path,
        tool_count=assessment.component_count,
        connection_count=assessment.connection_count,
        tools=[
            ToolInventoryResponse(
                name=item.operation,
                count=item.count,
                support=item.support,
            )
            for item in assessment.inventory
        ],
        complexity_score=assessment.complexity_score,
        complexity_band=assessment.complexity_band,
        recommended_target=assessment.recommended_target,
        target_components=list(assessment.target_components),
        recommendation_reason=assessment.recommendation_reason,
        unsupported_tools=list(assessment.unsupported_components),
        migration_wave=assessment.migration_wave,
        estimated_effort_days=assessment.estimated_effort_days,
        registry_version=assessment.registry_version,
        rules_version=assessment.rules_version,
        dependencies=list(assessment.dependencies),
        data_sources=list(assessment.data_sources),
        graph_schema_version="etl-ir-1.0.0",
        source_platform=assessment.source_platform,
        source_product=assessment.source_product,
        asset_type=assessment.asset_type,
        native_id=assessment.native_id,
        folder=assessment.folder,
        capacity_profile=capacity_profile,
    )
