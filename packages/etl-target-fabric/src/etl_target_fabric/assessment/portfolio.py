"""Shared application use cases."""

from dataclasses import replace
from pathlib import Path

from etl_migration_core.contracts.ir import SourcePlatform
from etl_migration_core.intake.discovery import DiscoveryService
from etl_migration_core.sources.defaults import create_default_registry
from etl_target_fabric.assessment.evaluator import apply_alteryx_native_route, apply_native_route
from etl_target_fabric.assessment.ir_assessment import EtlAssessment, assess_package
from etl_target_fabric.assessment.schemas import (
    DiscoverySummaryResponse,
    EstateAssessmentResponse,
    SkippedItemResponse,
    ToolInventoryResponse,
    WorkflowAssessmentResponse,
    WorkflowCandidateResponse,
)
from etl_target_fabric.assessment.workflow import WorkflowParseError, assess_workflow
from etl_target_fabric.capacity.model import (
    CapacityStaticProfile,
    build_capacity_profile,
    build_informatica_capacity_profile,
)


class FabricAssessmentApplication:
    """Coordinate discovery for all product entry points."""

    def __init__(self, discovery: DiscoveryService | None = None) -> None:
        self._discovery = discovery or DiscoveryService()
        self._source_registry = create_default_registry()

    def preview(self, path: Path) -> DiscoverySummaryResponse:
        """Build a pre-run summary for an untrusted local path."""
        summary = self._discovery.discover(path)
        return DiscoverySummaryResponse(
            input_path=summary.input_path,
            input_kind=summary.input_kind,
            workflow_count=summary.workflow_count,
            skipped_count=summary.skipped_count,
            total_size_bytes=summary.total_size_bytes,
            workflows=[
                WorkflowCandidateResponse.model_validate(candidate)
                for candidate in summary.workflows
            ],
            skipped=[SkippedItemResponse.model_validate(item) for item in summary.skipped],
        )

    def assess(
        self, path: Path, *, route_alteryx: bool = False
    ) -> EstateAssessmentResponse:
        """Assess every discovered workflow with per-file fault isolation."""
        summary = self._discovery.discover(path)
        assessments: list[WorkflowAssessmentResponse] = []
        failures: list[str] = []
        for candidate in summary.workflows:
            try:
                with self._discovery.staged_workflow(candidate) as workflow_path:
                    if candidate.source_platform is SourcePlatform.ALTERYX:
                        assessment = assess_workflow(workflow_path)
                        if route_alteryx:
                            assessment = apply_alteryx_native_route(workflow_path, assessment)
                        assessment = replace(assessment, path=candidate.display_path)
                        assessments.append(
                            WorkflowAssessmentResponse.model_validate(assessment).model_copy(
                                update={"capacity_profile": build_capacity_profile(workflow_path)}
                            )
                        )
                    else:
                        detected = self._source_registry.detect(
                            workflow_path,
                            candidate.display_path,
                        )
                        package = self._source_registry.parse(
                            workflow_path,
                            detected.match,
                        )
                        assessments.extend(
                            assessment_response(
                                candidate.display_path,
                                apply_native_route(package, asset, item),
                                capacity_profile=build_informatica_capacity_profile(
                                    package, asset
                                ),
                            )
                            for asset, item in zip(
                                package.assets,
                                assess_package(package),
                                strict=True,
                            )
                        )
            except WorkflowParseError as error:
                failures.append(str(error))
            except ValueError as error:
                failures.append(f"{candidate.display_path}: {error}")
        return EstateAssessmentResponse(
            workflow_count=len(assessments),
            failed_count=len(failures),
            assessments=assessments,
            failures=failures,
            workflows=[
                WorkflowCandidateResponse.model_validate(candidate)
                for candidate in summary.workflows
            ],
            skipped=[SkippedItemResponse.model_validate(item) for item in summary.skipped],
        )


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
