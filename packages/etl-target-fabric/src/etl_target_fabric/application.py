"""Fabric assessment use cases that compose static assessment with optional routing."""

from __future__ import annotations

from dataclasses import replace
from pathlib import Path

from etl_migration_core.contracts.ir import SourcePlatform
from etl_migration_core.intake.discovery import DiscoveryService
from etl_migration_core.sources.alteryx import AlteryxSourceAdapter
from etl_migration_core.sources.defaults import create_default_registry
from etl_migration_core.sources.registry import SourceAdapterRegistry
from etl_target_fabric.assessment.ir_assessment import assess_package
from etl_target_fabric.assessment.portfolio import assessment_response
from etl_target_fabric.assessment.schemas import (
    DiscoverySummaryResponse,
    EstateAssessmentResponse,
    SkippedItemResponse,
    WorkflowAssessmentResponse,
    WorkflowCandidateResponse,
)
from etl_target_fabric.assessment.workflow import WorkflowParseError, assess_workflow
from etl_target_fabric.capacity.model import (
    build_capacity_profile,
    build_informatica_capacity_profile,
)
from etl_target_fabric.evaluation.native_route import (
    apply_alteryx_native_route,
    apply_native_route,
)


class FabricAssessmentApplication:
    """Coordinate discovery for all product entry points."""

    def __init__(
        self,
        discovery: DiscoveryService | None = None,
        source_registry: SourceAdapterRegistry | None = None,
    ) -> None:
        if discovery is not None:
            self._discovery = discovery
            self._source_registry = source_registry or discovery.source_registry
        else:
            self._source_registry = source_registry or create_default_registry()
            self._discovery = DiscoveryService(source_registry=self._source_registry)

    def preview(self, path: Path) -> DiscoverySummaryResponse:
        """Build a pre-run summary for an untrusted local path."""
        return DiscoverySummaryResponse.from_summary(self._discovery.discover(path))

    def assess(
        self,
        path: Path,
        *,
        route_native: bool = False,
        route_alteryx: bool | None = None,
    ) -> EstateAssessmentResponse:
        """Assess every discovered workflow with per-file fault isolation.

        The default is the static portfolio assessment: no compiler runs. Pass
        ``route_native=True`` to confirm each route with the compilers, as the Fabric
        notebook does. ``route_alteryx`` is the earlier name for the same switch.
        """
        route = route_native if route_alteryx is None else route_alteryx
        summary = self._discovery.discover(path)
        assessments: list[WorkflowAssessmentResponse] = []
        failures: list[str] = []
        for candidate in summary.workflows:
            try:
                with self._discovery.staged_workflow(candidate) as workflow_path:
                    if candidate.source_platform is SourcePlatform.ALTERYX:
                        graph = AlteryxSourceAdapter().legacy_graph(workflow_path)
                        assessment = assess_workflow(workflow_path, graph=graph)
                        if route:
                            assessment = apply_alteryx_native_route(
                                workflow_path, assessment, graph=graph
                            )
                        assessment = replace(assessment, path=candidate.display_path)
                        assessments.append(
                            WorkflowAssessmentResponse.model_validate(assessment).model_copy(
                                update={
                                    "capacity_profile": build_capacity_profile(
                                        workflow_path, graph=graph
                                    )
                                }
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
                                apply_native_route(package, asset, item) if route else item,
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
