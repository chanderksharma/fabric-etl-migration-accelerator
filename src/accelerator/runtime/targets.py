"""Target-platform SPI evaluation, generation, and capacity orchestration."""

from __future__ import annotations

from collections.abc import Callable
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

from pydantic import ValidationError

from accelerator.runtime.identity import fabric_fit_key
from accelerator.runtime.models import (
    TARGET_EVALUATION_LIST,
    Run,
    RunTargetEvaluation,
    SnapshotPreview,
)
from accelerator.runtime.store import RunStore
from etl_migration_core.contracts.ir import EtlPackage, SourcePlatform
from etl_migration_core.contracts.spi import (
    TargetCapacityResult,
    TargetGenerationResult,
    TargetPlatformProvider,
)
from etl_migration_core.intake.schemas import WorkflowCandidateResponse
from etl_migration_core.sources.alteryx.graph import WorkflowParseError
from etl_migration_core.targets.registry import TargetPlatformRegistry
from etl_target_fabric.assessment.schemas import (
    EstateAssessmentResponse,
    WorkflowAssessmentResponse,
)
from etl_target_fabric.evaluation import confirm_assessment
from etl_target_fabric.provider import FabricTargetProvider

FABRIC_PLATFORM_ID = "fabric"


class TargetOrchestrator:
    """Coordinate pluggable target evaluations, previews, and capacity via Target SPI."""

    def __init__(
        self,
        store: RunStore,
        parse_item: Callable[[WorkflowCandidateResponse], EtlPackage],
        *,
        max_workers: int = 4,
    ) -> None:
        self._store = store
        self._parse_item = parse_item
        self._max_workers = max(1, max_workers)

    def current_fabric_fit(self, identity: str) -> list[RunTargetEvaluation] | None:
        """Return stored Fabric evaluations if present and matching current compiler versions."""
        with self._store.connection() as connection:
            row = connection.execute(
                "SELECT evaluations_json FROM target_evaluations WHERE run_id=? AND platform_id=?",
                (identity, FABRIC_PLATFORM_ID),
            ).fetchone()
        if row is None:
            return None
        try:
            evaluations = TARGET_EVALUATION_LIST.validate_json(row["evaluations_json"])
        except ValidationError:
            return None
        key = fabric_fit_key(FabricTargetProvider.provider_version)
        if any(item.evaluation_key != key for item in evaluations):
            return None
        return evaluations

    def confirmed_result(
        self, identity: str, result: EstateAssessmentResponse
    ) -> EstateAssessmentResponse | None:
        """Overlay a valid stored Fabric evaluation onto a static assessment result."""
        evaluations = self.current_fabric_fit(identity)
        if evaluations is None:
            return None
        by_path = {
            item.assessment_path: item.evaluation
            for item in evaluations
            if item.assessment_path is not None
        }
        if any(assessment.path not in by_path for assessment in result.assessments):
            return None
        return result.model_copy(
            update={
                "assessments": [
                    confirm_assessment(assessment, by_path[assessment.path])
                    for assessment in result.assessments
                ]
            }
        )

    def evaluate_target(
        self,
        identity: str,
        run: Run,
        basis: str | None,
        snapshot: SnapshotPreview,
        platform_id: str,
        registry: TargetPlatformRegistry,
    ) -> list[RunTargetEvaluation]:
        """Evaluate every confirmed workflow asset against a registered target provider."""
        if run.status != "completed":
            raise ValueError("Complete an assessment before evaluating a target")
        provider = registry.require_implemented(platform_id, capability="evaluate")
        confirms = (
            provider.platform_id.strip().casefold() == FABRIC_PLATFORM_ID
            and basis is not None
            and run.result is not None
        )
        static = (
            {item.path: item for item in run.result.assessments}
            if confirms and run.result is not None
            else {}
        )
        key = fabric_fit_key(provider.provider_version) if confirms else None
        workflows = snapshot.workflows
        if len(workflows) <= 1 or self._max_workers == 1:
            grouped = [
                self._evaluate_item(item, provider, registry, static, key)
                for item in workflows
            ]
        else:
            workers = min(self._max_workers, len(workflows))
            with ThreadPoolExecutor(max_workers=workers) as executor:
                grouped = list(
                    executor.map(
                        lambda item: self._evaluate_item(item, provider, registry, static, key),
                        workflows,
                    )
                )
        evaluations = [record for chunk in grouped for record in chunk]
        with self._store.connection() as connection:
            connection.execute(
                """INSERT INTO target_evaluations
                (run_id, platform_id, provider_version, evaluations_json)
                VALUES (?, ?, ?, ?)
                ON CONFLICT(run_id, platform_id) DO UPDATE SET
                    provider_version=excluded.provider_version,
                    evaluations_json=excluded.evaluations_json""",
                (
                    identity,
                    provider.platform_id.strip().casefold(),
                    provider.provider_version,
                    TARGET_EVALUATION_LIST.dump_json(evaluations).decode("utf-8"),
                ),
            )
        return evaluations

    def _evaluate_item(
        self,
        item: WorkflowCandidateResponse,
        provider: TargetPlatformProvider,
        registry: TargetPlatformRegistry,
        static: dict[str, WorkflowAssessmentResponse],
        key: str | None,
    ) -> list[RunTargetEvaluation]:
        built_in = isinstance(item.source_platform, SourcePlatform)
        try:
            package = self._parse_item(item)
        except (WorkflowParseError, ValueError):
            if key is not None and built_in:
                return []
            raise
        alteryx = item.source_platform is SourcePlatform.ALTERYX
        assets = package.assets[:1] if key is not None and alteryx else package.assets
        records: list[RunTargetEvaluation] = []
        for asset in assets:
            assessed: WorkflowAssessmentResponse | None = None
            assessment_path: str | None = None
            if key is not None and built_in:
                asset_path = "/".join(part for part in (asset.folder, asset.name) if part)
                assessment_path = (
                    item.display_path
                    if alteryx or not asset_path
                    else f"{item.display_path}!{asset_path}"
                )
                assessed = static.get(assessment_path)
                if assessed is None:
                    continue
            if assessed is not None and alteryx:
                evaluation = registry.evaluate_alteryx_path(
                    provider.platform_id,
                    Path(item.source_path),
                    unsupported_tools=assessed.unsupported_tools,
                    default_target=assessed.recommended_target,
                    default_components=assessed.target_components,
                    default_reason=assessed.recommendation_reason,
                )
            else:
                evaluation = registry.evaluate_asset(
                    provider.platform_id,
                    package,
                    asset,
                    base_reason=(
                        assessed.recommendation_reason
                        if assessed is not None
                        else f"Evaluated {asset.name}"
                    ),
                )
            records.append(
                RunTargetEvaluation(
                    source_path=item.display_path,
                    asset_id=asset.native_id,
                    asset_name=asset.name,
                    ir_version=package.ir_version,
                    provider_version=provider.provider_version,
                    evaluation=evaluation,
                    assessment_path=assessment_path if assessed is not None else None,
                    evaluation_key=key if assessed is not None else None,
                )
            )
        return records

    def get_evaluations(self, identity: str, platform_id: str) -> list[RunTargetEvaluation]:
        """Return the last saved evaluation for one run and target platform."""
        with self._store.connection() as connection:
            row = connection.execute(
                "SELECT evaluations_json FROM target_evaluations WHERE run_id=? AND platform_id=?",
                (identity, platform_id.strip().casefold()),
            ).fetchone()
        if row is None:
            raise KeyError("No saved evaluation exists for this run and target")
        return TARGET_EVALUATION_LIST.validate_json(row["evaluations_json"])

    def generate_for_target(
        self,
        snapshot: SnapshotPreview,
        platform_id: str,
        target_kind: str,
        registry: TargetPlatformRegistry,
    ) -> list[TargetGenerationResult]:
        """Generate target-neutral artifact previews via TargetCodeGeneratorProvider."""
        workflows = snapshot.workflows

        def _generate_one(item: WorkflowCandidateResponse) -> TargetGenerationResult:
            package = self._parse_item(item)
            return registry.generate_package(
                platform_id,
                package,
                target_kind=target_kind,
                display_path=item.display_path,
            )

        if len(workflows) <= 1 or self._max_workers == 1:
            return [_generate_one(item) for item in workflows]
        workers = min(self._max_workers, len(workflows))
        with ThreadPoolExecutor(max_workers=workers) as executor:
            return list(executor.map(_generate_one, workflows))

    def estimate_capacity(
        self,
        snapshot: SnapshotPreview,
        platform_id: str,
        registry: TargetPlatformRegistry,
    ) -> list[TargetCapacityResult]:
        """Estimate capacity for confirmed assets via a registered TargetCapacityProvider."""
        workflows = snapshot.workflows

        def _estimate_one(item: WorkflowCandidateResponse) -> TargetCapacityResult:
            package = self._parse_item(item)
            return registry.estimate_capacity(platform_id, package)

        if len(workflows) <= 1 or self._max_workers == 1:
            return [_estimate_one(item) for item in workflows]
        workers = min(self._max_workers, len(workflows))
        with ThreadPoolExecutor(max_workers=workers) as executor:
            return list(executor.map(_estimate_one, workflows))
