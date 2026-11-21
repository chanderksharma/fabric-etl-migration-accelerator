"""Stateless target-neutral portfolio assessment application facade."""

from __future__ import annotations

from pathlib import Path

from etl_migration_core.discovery import DiscoveryService
from etl_migration_core.graph import WorkflowParseError
from etl_migration_core.sources.defaults import create_default_registry
from etl_migration_core.sources.registry import SourceAdapterRegistry
from etl_portfolio_assessment.engine import assess_package_neutral
from etl_portfolio_assessment.evidence import WorkflowEvidence, etl_asset_evidence
from etl_portfolio_assessment.schemas import (
    DiscoverySummaryResponse,
    NeutralAssessmentResponse,
    NeutralComponentResponse,
    NeutralEstateAssessmentResponse,
    SkippedItemResponse,
    WorkflowCandidateResponse,
)
from etl_portfolio_assessment.workload_profile import extract_workload_profile


class PortfolioAssessmentApplication:
    """Coordinate discovery and target-neutral portfolio assessment."""

    def __init__(
        self,
        discovery: DiscoveryService | None = None,
        source_registry: SourceAdapterRegistry | None = None,
    ) -> None:
        self._discovery = discovery or DiscoveryService()
        self._source_registry = source_registry or create_default_registry()

    def preview(self, path: Path) -> DiscoverySummaryResponse:
        """Build a pre-run discovery summary for an untrusted local path."""
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

    def assess_neutral(self, path: Path) -> NeutralEstateAssessmentResponse:
        """Assess discovered assets purely by source semantics without target bias."""
        summary = self._discovery.discover(path)
        assessments: list[NeutralAssessmentResponse] = []
        failures: list[str] = []
        for candidate in summary.workflows:
            try:
                with self._discovery.staged_workflow(candidate) as workflow_path:
                    detected = self._source_registry.detect(
                        workflow_path,
                        candidate.display_path,
                    )
                    package = self._source_registry.parse(
                        workflow_path,
                        detected.match,
                    )
                    for asset, item in zip(
                        package.assets,
                        assess_package_neutral(package),
                        strict=True,
                    ):
                        asset_path = "/".join(
                            part for part in (item.folder, item.name) if part
                        )
                        display = (
                            f"{candidate.display_path}!{asset_path}"
                            if asset_path
                            else candidate.display_path
                        )
                        assessments.append(
                            NeutralAssessmentResponse(
                                path=display,
                                native_id=item.native_id,
                                name=item.name,
                                folder=item.folder,
                                source_platform=item.source_platform,
                                source_product=item.source_product,
                                asset_type=item.asset_type,
                                component_count=item.component_count,
                                connection_count=item.connection_count,
                                inventory=[
                                    NeutralComponentResponse.model_validate(entry)
                                    for entry in item.inventory
                                ],
                                complexity_score=item.complexity_score,
                                complexity_band=item.complexity_band,
                                intrinsic_effort_days=item.intrinsic_effort_days,
                                wave_tier=item.wave_tier,
                                unknown_components=list(item.unknown_components),
                                dependencies=list(item.dependencies),
                                data_sources=list(item.data_sources),
                                rules_version=item.rules_version,
                                workload_profile=extract_workload_profile(
                                    package, asset
                                ),
                            )
                        )
            except WorkflowParseError as error:
                failures.append(str(error))
            except ValueError as error:
                failures.append(f"{candidate.display_path}: {error}")
        return NeutralEstateAssessmentResponse(
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

    def inspect_evidence(self, path: Path) -> list[WorkflowEvidence]:
        """Extract redacted graph evidence from discovered assets."""
        summary = self._discovery.discover(path)
        items: list[WorkflowEvidence] = []
        for index, candidate in enumerate(summary.workflows):
            with self._discovery.staged_workflow(candidate) as workflow_path:
                detected = self._source_registry.detect(
                    workflow_path,
                    candidate.display_path,
                )
                package = self._source_registry.parse(
                    workflow_path,
                    detected.match,
                )
                items.extend(
                    etl_asset_evidence(package, asset, candidate.display_path, index)
                    for asset in package.assets
                )
        return items
