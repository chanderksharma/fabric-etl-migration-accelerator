"""Shared application use cases combining Fabric and target-neutral assessment."""

from __future__ import annotations

from pathlib import Path

from etl_migration_core.discovery import DiscoveryService
from etl_migration_core.graph import WorkflowParseError
from etl_migration_core.spi import NeutralWorkloadProfile
from etl_portfolio_assessment.engine import (
    NeutralAssetAssessment,
    assess_package_neutral,
)
from etl_portfolio_assessment.workload_profile import extract_workload_profile
from etl_target_fabric.portfolio import (
    FabricAssessmentApplication,
)
from etl_target_fabric.portfolio import (
    assessment_response as assessment_response,
)


class AssessmentApplication(FabricAssessmentApplication):
    """Coordinate preview, Fabric-routed assessment, and neutral assessment."""

    def __init__(self, discovery: DiscoveryService | None = None) -> None:
        super().__init__(discovery=discovery)

    def assess_neutral(
        self, path: Path
    ) -> tuple[list[tuple[NeutralAssetAssessment, NeutralWorkloadProfile]], list[str]]:
        """Run purely target-neutral portfolio assessment across all source platforms."""
        summary = self._discovery.discover(path)
        results: list[tuple[NeutralAssetAssessment, NeutralWorkloadProfile]] = []
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
                    assessments = assess_package_neutral(package)
                    for asset, item in zip(
                        package.assets,
                        assessments,
                        strict=True,
                    ):
                        results.append(
                            (item, extract_workload_profile(package, asset))
                        )
            except WorkflowParseError as error:
                failures.append(str(error))
            except ValueError as error:
                failures.append(f"{candidate.display_path}: {error}")
        return results, failures
