"""Immutable local snapshots, durable jobs, and context-keyed incremental results."""

import csv
import hashlib
import io
import json
import logging
import re
import sqlite3
import tempfile
import time
import uuid
from collections.abc import Callable, Iterator
from concurrent.futures import FIRST_COMPLETED, Future, ThreadPoolExecutor, wait
from contextlib import AbstractContextManager, contextmanager
from dataclasses import replace
from pathlib import Path
from typing import Self

from pydantic import TypeAdapter, ValidationError

from accelerator.runtime.artifacts import project_candidate
from accelerator.runtime.identity import (
    assessment_cache_key,
    candidate_cache_key,
    fabric_fit_key,
    ir_cache_key,
    neutral_cache_key,
)
from accelerator.runtime.identity import copy_with_sha256 as _copy_with_sha256
from accelerator.runtime.identity import sha256_file as _sha256_file
from accelerator.runtime.identity import snapshot_id as _snapshot_id
from accelerator.runtime.models import (
    TARGET_EVALUATION_LIST,
    ArtifactPublication,
    GenerationJob,
    Run,
    RunStatus,
    RunTargetEvaluation,
    SnapshotPreview,
)
from accelerator.runtime.publication import (
    MANIFEST_NAME,
    build_archive,
    build_manifest,
    check_tree,
    manifest_bytes,
    manifest_digest,
    read_manifest,
)
from accelerator.runtime.store import GarbageReport, RunStore
from accelerator.settings import Settings
from etl_migration_core.contracts.ir import (
    IR_VERSION,
    EtlAsset,
    EtlPackage,
    SourcePlatform,
)
from etl_migration_core.contracts.spi import (
    TargetCapacityResult,
    TargetGenerationResult,
    TargetPlatformProvider,
)
from etl_migration_core.intake.discovery import DiscoveryService, hash_idmc_directory
from etl_migration_core.plugins import fault_detail
from etl_migration_core.sources.alteryx import AlteryxSourceAdapter
from etl_migration_core.sources.alteryx.graph import (
    WorkflowGraph,
    WorkflowParseError,
    redact,
)
from etl_migration_core.sources.defaults import create_default_registry
from etl_migration_core.sources.registry import SourceAdapterRegistry
from etl_migration_core.targets.registry import TargetPlatformRegistry
from etl_portfolio_assessment.evidence.extractor import (
    EvidenceResponse,
    etl_asset_evidence,
    workflow_evidence,
)
from etl_portfolio_assessment.service.application import neutral_assessment_responses
from etl_portfolio_assessment.service.schemas import (
    NeutralAssessmentResponse,
    NeutralEstateAssessmentResponse,
)
from etl_portfolio_assessment.service.schemas import (
    SkippedItemResponse as NeutralSkippedItemResponse,
)
from etl_portfolio_assessment.service.schemas import (
    WorkflowCandidateResponse as NeutralWorkflowCandidateResponse,
)
from etl_target_fabric.assessment.ir_assessment import (
    ASSESSMENT_RULES_VERSION,
    REGISTRY_VERSIONS,
    assess_package,
)
from etl_target_fabric.assessment.portfolio import assessment_response
from etl_target_fabric.assessment.schemas import (
    EstateAssessmentResponse,
    SkippedItemResponse,
    WorkflowAssessmentResponse,
    WorkflowCandidateResponse,
)
from etl_target_fabric.assessment.support_matrix import (
    alteryx_support_for,
    etl_support_for,
)
from etl_target_fabric.assessment.workflow import (
    assess_workflow,
)
from etl_target_fabric.capacity.model import (
    CapacityPortfolioEstimate,
    CapacitySettings,
    CapacityUpdate,
    CapacityWorkflowInput,
    build_informatica_capacity_profile,
    capacity_csv,
    estimate_capacity,
)
from etl_target_fabric.compilers.alteryx import (
    Candidate,
    Target,
    generate_candidate,
)
from etl_target_fabric.compilers.ir import (
    ETL_COMPILER_VERSION,
    EtlCompiledCandidate,
    compile_asset,
)
from etl_target_fabric.delivery.artifact_writer import (
    ArtifactWriteResult,
    _artifact_path,
    build_candidate_package,
    build_workflow_package,
    write_candidates,
)
from etl_target_fabric.evaluation import confirm_assessment
from etl_target_fabric.provider import FabricTargetProvider

ASSESSMENT_LIST = TypeAdapter(list[WorkflowAssessmentResponse])
NEUTRAL_LIST = TypeAdapter(list[NeutralAssessmentResponse])
LEASE_SECONDS = 300
LEASE_RENEWAL_INTERVAL_SECONDS = 60
WORKER_POLL_SECONDS = 5
MAX_RUN_ATTEMPTS = 5
ALL_TARGETS: tuple[Target, ...] = ("dataflow", "notebook", "pipeline")
FABRIC_PLATFORM_ID = "fabric"
# Written when a run completes. Assessment never runs a compiler, so its Fabric routing is
# the static support-matrix mapping until a stored Fabric evaluation confirms it.
STATIC_ASSESSMENT_BASIS = "static_mapping"

logger = logging.getLogger(__name__)

AssessmentOutcome = tuple[
    list[WorkflowAssessmentResponse],
    str | None,
    int,
    list[NeutralAssessmentResponse],
    str | None,
]


class _LeaseLost(Exception):
    """The generation job lease was claimed by another worker."""


def _blocked_generation_candidate(
    item: WorkflowCandidateResponse, target: Target, message: str
) -> Candidate:
    platform = item.source_platform
    return Candidate(
        workflow=item.display_path,
        target=target,
        validation_state="blocked",
        translation_mode="scaffold",
        source_sha256=item.sha256,
        code_sha256=hashlib.sha256(message.encode()).hexdigest(),
        diagnostics=[message],
        source_platform=(
            platform if isinstance(platform, SourcePlatform) else SourcePlatform.ALTERYX
        ),
    )


def _generation_job(row: sqlite3.Row) -> GenerationJob:
    payload = row["result"]
    return GenerationJob(
        id=row["id"],
        run_id=row["run_id"],
        target=row["target"],
        status=row["status"],
        attempts=row["attempts"],
        error=row["error"],
        candidates=TypeAdapter(list[Candidate]).validate_json(payload) if payload else None,
    )


def _unexpected_failure(item: WorkflowCandidateResponse, error: Exception) -> str:
    """Record an unexpected fault as one failed workflow so the rest of the run completes."""
    logger.error("Unexpected fault while assessing %s", item.display_path, exc_info=error)
    return f"{item.display_path}: unexpected {redact(fault_detail(error))}"


__all__ = [
    "ArtifactWriteResult",
    "Run",
    "RunService",
    "RunStatus",
    "RunTargetEvaluation",
    "SnapshotPreview",
    "_artifact_path",
]


class RunService:
    """Single-host WAL store with atomic work claims and commit fencing."""

    def __init__(
        self,
        root: Path,
        artifact_root: Path | None = None,
        source_registry: SourceAdapterRegistry | None = None,
    ) -> None:
        self.root = root
        self.artifact_root = artifact_root or root.parent / "generated-fabric-workflows"
        self._source_registry = source_registry or create_default_registry()
        self._discovery = DiscoveryService(source_registry=self._source_registry)
        self._store = RunStore(root)
        self.database = self._store.database

    @classmethod
    def from_settings(cls, settings: Settings) -> Self:
        """Build the service the way every entry point should: one settings object."""
        return cls(
            settings.state_dir,
            artifact_root=settings.artifact_dir,
            source_registry=create_default_registry(plugin_allowlist=settings.plugin_allowlist),
        )

    @property
    def closed(self) -> bool:
        return self._store.closed

    @property
    def source_registry(self) -> SourceAdapterRegistry:
        """Return the active source adapter registry."""
        return self._source_registry

    def _connection(self) -> AbstractContextManager[sqlite3.Connection]:
        return self._store.connection()

    def __enter__(self) -> Self:
        if self.closed:
            raise ValueError("Run store is closed")
        return self

    def __exit__(self, *_error: object) -> None:
        self.close()

    def close(self) -> None:
        self._store.close()

    def collect_garbage(
        self, *, max_age_days: float = 30, max_cache_bytes: int = 512 * 1024 * 1024, dry_run: bool
    ) -> GarbageReport:
        """Apply the retention policy to runs, snapshots, publications, and caches."""
        return self._store.collect_garbage(
            max_age_days=max_age_days, max_cache_bytes=max_cache_bytes, dry_run=dry_run
        )

    def preview(self, source: Path) -> SnapshotPreview:
        started = time.perf_counter()
        summary = self._discovery.discover(source)
        snapshot_id = _snapshot_id(summary.workflows)
        folder = self.root / "snapshots" / snapshot_id
        folder.mkdir(parents=True, exist_ok=True)
        files: list[WorkflowCandidateResponse] = []
        for index, candidate in enumerate(summary.workflows):
            destination = folder / f"{index}{candidate.extension}"
            if not destination.exists():
                with tempfile.TemporaryDirectory(dir=folder) as temporary:
                    staging = Path(temporary) / "snapshot"
                    with self._discovery.staged_workflow(candidate) as original:
                        staged_sha256 = (
                            hash_idmc_directory(original, destination=staging)[0]
                            if original.is_dir()
                            else _copy_with_sha256(original, staging)
                        )
                    if staged_sha256 != candidate.sha256:
                        raise ValueError(
                            "Source changed during preview; review the selection again"
                        )
                    try:
                        staging.replace(destination)
                    except OSError:
                        if (
                            not destination.exists()
                            or _sha256_file(destination) != candidate.sha256
                        ):
                            raise
            elif _sha256_file(destination) != candidate.sha256:
                raise ValueError("Source changed during preview; review the selection again")
            files.append(
                WorkflowCandidateResponse.model_validate(
                    replace(
                        candidate, source_path=str(destination), archive_path=None, archive_chain=()
                    )
                )
            )
        preview = SnapshotPreview(
            input_path=summary.input_path,
            input_kind=summary.input_kind,
            workflow_count=summary.workflow_count,
            skipped_count=summary.skipped_count,
            total_size_bytes=summary.total_size_bytes,
            skipped=[SkippedItemResponse.model_validate(item) for item in summary.skipped],
            workflows=files,
            snapshot_id=snapshot_id,
        )
        with self._connection() as connection:
            connection.execute(
                """INSERT INTO snapshots (id, preview, created_at) VALUES (?, ?, ?)
                ON CONFLICT(id) DO UPDATE SET
                    preview=excluded.preview, created_at=excluded.created_at""",
                (snapshot_id, preview.model_dump_json(), time.time()),
            )
        logger.info(
            "Snapshot %s: %d workflows, %d skipped, %.0f ms",
            snapshot_id[:12],
            preview.workflow_count,
            preview.skipped_count,
            (time.perf_counter() - started) * 1000,
        )
        return preview

    def _snapshot(self, snapshot_id: str) -> SnapshotPreview:
        with self._connection() as connection:
            row = connection.execute(
                "SELECT preview FROM snapshots WHERE id=?", (snapshot_id,)
            ).fetchone()
        if row is None:
            raise KeyError("Snapshot not found; review the selection again")
        preview = SnapshotPreview.model_validate_json(row["preview"])
        if _snapshot_id(preview.workflows) != snapshot_id:
            raise ValueError("Snapshot engine versions changed; review the selection again")
        for item in preview.workflows:
            path = Path(item.source_path)
            if _sha256_file(path) != item.sha256:
                raise ValueError("Confirmed snapshot changed; review the selection again")
            if not isinstance(item.source_platform, SourcePlatform):
                detected = self._source_registry.detect(path, item.display_path)
                if (
                    detected.adapter.adapter_id != item.adapter_id
                    or detected.match.platform != item.source_platform
                    or detected.adapter.adapter_version != item.adapter_version
                    or not all((item.parser_version, item.registry_version, item.rules_version))
                    or detected.adapter.parser_version != item.parser_version
                    or detected.adapter.registry_version != item.registry_version
                    or detected.adapter.rules_version != item.rules_version
                ):
                    raise ValueError("Confirmed source adapter changed; review the selection again")
        return preview

    def create_run(self, snapshot_id: str) -> Run:
        preview = self._snapshot(snapshot_id)
        if not preview.workflows:
            raise ValueError("No supported workflows were found; select a different input")
        identity = uuid.uuid4().hex
        with self._connection() as connection:
            connection.execute(
                "INSERT INTO runs (id,snapshot,status,total,created_at) VALUES (?,?,'queued',?,?)",
                (identity, snapshot_id, preview.workflow_count, time.time()),
            )
        return self.get_run(identity)

    def _read_run(self, identity: str, *, include_result: bool) -> tuple[Run, str | None]:
        """Read one run as stored, with the routing basis recorded when it completed."""
        with self._connection() as connection:
            columns = (
                "id, snapshot, status, processed, total, cache_hits, error, timings, "
                "assessment_basis, result"
                if include_result
                else "id, snapshot, status, processed, total, cache_hits, error, timings, "
                "assessment_basis"
            )
            row = connection.execute(
                f"SELECT {columns} FROM runs WHERE id=?", (identity,)
            ).fetchone()
        if row is None:
            raise KeyError("Run not found")
        run = Run(
            id=row["id"],
            snapshot_id=row["snapshot"],
            status=row["status"],
            processed=row["processed"],
            total=row["total"],
            cache_hits=row["cache_hits"],
            error=row["error"],
            timings=json.loads(row["timings"]) if row["timings"] else None,
            result=(
                EstateAssessmentResponse.model_validate_json(row["result"])
                if include_result and row["result"]
                else None
            ),
        )
        return run, row["assessment_basis"]

    def get_run(self, identity: str, *, include_result: bool = True) -> Run:
        """Return a run, applying a current Fabric evaluation to its routing fields.

        The stored assessment is static. When a Fabric evaluation computed with the current
        compiler and rules exists, ``confirm_assessment`` overlays its target, wave, and
        effort so consumers of the legacy fields keep working, and ``routing_basis``
        says so. A run stored before assessment stopped compiling has no recorded basis and
        is returned unchanged: its stored routing already came from the compilers.
        """
        run, basis = self._read_run(identity, include_result=include_result)
        if run.result is None or run.status != "completed":
            return run
        if basis is None:
            return run.model_copy(update={"routing_basis": "compiler_confirmed"})
        confirmed = self._confirmed_result(identity, run.result)
        if confirmed is None:
            return run
        return run.model_copy(update={"result": confirmed, "routing_basis": "compiler_confirmed"})

    def _current_fabric_fit(self, identity: str) -> list[RunTargetEvaluation] | None:
        """Return the Fabric evaluation, or None if absent or computed with other versions."""
        with self._connection() as connection:
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

    def _confirmed_result(
        self, identity: str, result: EstateAssessmentResponse
    ) -> EstateAssessmentResponse | None:
        """Apply a stored Fabric evaluation to a static result, or None if it does not cover it."""
        evaluations = self._current_fabric_fit(identity)
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

    def ensure_fabric_fit(self, identity: str) -> Run:
        """Return the run with Fabric routing confirmed, evaluating it first when needed.

        Generation consumes the Fabric evaluation (the deployment bundle follows the confirmed
        target components), so it asks for it here instead of reading assessment output that
        was never routed. A run with nothing assessed has nothing to confirm.
        """
        run = self.get_run(identity)
        if (
            run.status == "completed"
            and run.result is not None
            and run.result.assessments
            and run.routing_basis == "static_mapping"
        ):
            self.evaluate_target(
                identity, FABRIC_PLATFORM_ID, TargetPlatformRegistry((FabricTargetProvider(),))
            )
            run = self.get_run(identity)
        return run

    def get_run_status(self, identity: str) -> RunStatus:
        """Return lightweight run status without reading or validating result JSON."""
        run = self.get_run(identity, include_result=False)
        return RunStatus(
            id=run.id,
            snapshot_id=run.snapshot_id,
            status=run.status,
            processed=run.processed,
            total=run.total,
            cache_hits=run.cache_hits,
            error=run.error,
            timings=run.timings,
        )

    def pending(self) -> list[str]:
        with self._connection() as connection:
            return [
                row["id"]
                for row in connection.execute(
                    "SELECT id FROM runs WHERE status='queued' OR (status='running' AND lease<?)",
                    (time.time(),),
                )
            ]

    def _claim(self, identity: str) -> int | None:
        with self._connection() as connection:
            connection.execute("BEGIN IMMEDIATE")
            now = time.time()
            claimable = connection.execute(
                """SELECT attempts FROM runs
                WHERE id=? AND (status='queued' OR (status='running' AND lease<?))""",
                (identity, now),
            ).fetchone()
            if claimable is None:
                return None
            if claimable["attempts"] >= MAX_RUN_ATTEMPTS:
                logger.error("Run %s abandoned after %s attempts", identity, MAX_RUN_ATTEMPTS)
                connection.execute(
                    "UPDATE runs SET status='failed', error=?, lease=0 WHERE id=?",
                    (
                        f"Run abandoned after {MAX_RUN_ATTEMPTS} interrupted attempts; "
                        "a workflow may be crashing the process. Remove it and start a new run.",
                        identity,
                    ),
                )
                return None
            connection.execute(
                """UPDATE runs SET status='running', epoch=epoch+1, attempts=attempts+1, lease=?
                WHERE id=?""",
                (now + LEASE_SECONDS, identity),
            )
            return int(
                connection.execute("SELECT epoch FROM runs WHERE id=?", (identity,)).fetchone()[
                    "epoch"
                ]
            )

    def execute(self, identity: str) -> None:
        epoch = self._claim(identity)
        if epoch is None:
            return
        started = time.perf_counter()
        run = self.get_run(identity, include_result=False)
        assessments: list[WorkflowAssessmentResponse] = []
        failures: list[str] = []
        neutral_assessments: list[NeutralAssessmentResponse] = []
        neutral_failures: list[str] = []
        hits = 0
        try:
            snapshot = self._snapshot(run.snapshot_id)
            with self._connection() as connection:
                active = connection.execute(
                    "SELECT 1 FROM runs WHERE id=? AND epoch=? AND status='running'",
                    (identity, epoch),
                ).fetchone()
                if active is None:
                    return
            verified = time.perf_counter()
            with ThreadPoolExecutor(max_workers=4) as executor:
                work = iter(enumerate(snapshot.workflows))
                pending: dict[Future[AssessmentOutcome], int] = {}
                outcomes: dict[int, AssessmentOutcome] = {}

                def fill_slots() -> None:
                    while len(pending) < 4:
                        try:
                            index, item = next(work)
                        except StopIteration:
                            break
                        pending[executor.submit(self._assess_item_with_neutral, item)] = index

                fill_slots()
                while pending:
                    completed, _ = wait(
                        pending, timeout=WORKER_POLL_SECONDS, return_when=FIRST_COMPLETED
                    )
                    with self._connection() as connection:
                        lease_row = connection.execute(
                            """SELECT lease FROM runs
                            WHERE id=? AND epoch=? AND status='running'""",
                            (identity, epoch),
                        ).fetchone()
                        if lease_row is None:
                            return
                        if completed:
                            for future in completed:
                                index = pending.pop(future)
                                outcome = future.result()
                                outcomes[index] = outcome
                                hits += outcome[2]
                            lease_updated = connection.execute(
                                """UPDATE runs SET processed=?, cache_hits=?, lease=?
                                WHERE id=? AND epoch=? AND status='running'""",
                                (
                                    len(outcomes),
                                    hits,
                                    time.time() + LEASE_SECONDS,
                                    identity,
                                    epoch,
                                ),
                            ).rowcount
                        elif lease_row["lease"] <= time.time() + LEASE_RENEWAL_INTERVAL_SECONDS:
                            lease_updated = connection.execute(
                                """UPDATE runs SET lease=?
                                WHERE id=? AND epoch=? AND status='running'""",
                                (time.time() + LEASE_SECONDS, identity, epoch),
                            ).rowcount
                        else:
                            lease_updated = 1
                        if not lease_updated:
                            return
                    fill_slots()
                for index in sorted(outcomes):
                    (
                        item_assessments,
                        failure,
                        _hit,
                        item_neutral,
                        neutral_failure,
                    ) = outcomes[index]
                    assessments.extend(item_assessments)
                    if failure is not None:
                        failures.append(failure)
                    neutral_assessments.extend(item_neutral)
                    if neutral_failure is not None:
                        neutral_failures.append(neutral_failure)
            assessed = time.perf_counter()
            result = EstateAssessmentResponse(
                workflow_count=len(assessments),
                failed_count=len(failures),
                assessments=assessments,
                failures=failures,
                workflows=snapshot.workflows,
                skipped=snapshot.skipped,
            )
            neutral_result = _neutral_estate(snapshot, neutral_assessments, neutral_failures)
            result_json = result.model_dump_json()
            neutral_json = neutral_result.model_dump_json()
            persisted = time.perf_counter()
            timings = {
                "verify_ms": round((verified - started) * 1000, 1),
                "assess_ms": round((assessed - verified) * 1000, 1),
                "persist_ms": round((persisted - assessed) * 1000, 1),
                "total_ms": round((persisted - started) * 1000, 1),
            }
            with self._connection() as connection:
                updated = connection.execute(
                    """UPDATE runs SET status='completed', result=?, timings=?,
                    assessment_basis=?, lease=0
                    WHERE id=? AND epoch=? AND status='running'""",
                    (
                        result_json,
                        json.dumps(timings),
                        STATIC_ASSESSMENT_BASIS,
                        identity,
                        epoch,
                    ),
                )
                if updated.rowcount:
                    connection.execute(
                        """INSERT INTO neutral_assessments (run_id, assessment_json) VALUES (?, ?)
                        ON CONFLICT(run_id) DO UPDATE SET
                        assessment_json=excluded.assessment_json""",
                        (identity, neutral_json),
                    )
            logger.info(
                "Run %s completed: %d assessments, %d failures, %d cache hits, %s",
                identity,
                len(assessments),
                len(failures),
                hits,
                ", ".join(f"{name}={value:g}" for name, value in timings.items()),
            )
        except Exception as error:
            expected = isinstance(error, OSError | ValueError | KeyError | sqlite3.Error)
            if not expected:
                logger.exception("Run %s failed unexpectedly", identity)
            with self._connection() as connection:
                connection.execute(
                    """UPDATE runs SET status='failed',error=?,lease=0
                    WHERE id=? AND epoch=? AND status='running'""",
                    (
                        redact(str(error) if expected else f"Unexpected {fault_detail(error)}"),
                        identity,
                        epoch,
                    ),
                )

    def cancel(self, identity: str) -> Run:
        self.get_run(identity)
        with self._connection() as connection:
            connection.execute(
                """UPDATE runs SET status='cancelled',epoch=epoch+1,lease=0
                WHERE id=? AND status IN ('queued','running')""",
                (identity,),
            )
        return self.get_run(identity)

    def get_capacity(self, identity: str) -> CapacityPortfolioEstimate:
        """Return the deterministic capacity estimate for a completed run."""
        run = self.get_run(identity)
        return self._estimate_capacity_for_run(identity, run)

    def _estimate_capacity_for_run(
        self, identity: str, run: Run
    ) -> CapacityPortfolioEstimate:
        if run.status != "completed" or run.result is None:
            raise ValueError("Complete an assessment before estimating capacity")
        defaults = {
            assessment.path: CapacityWorkflowInput(workflow_path=assessment.path)
            for assessment in run.result.assessments
            if assessment.capacity_profile is not None
        }
        with self._connection() as connection:
            settings_row = connection.execute(
                "SELECT settings_json FROM capacity_settings WHERE run_id=?",
                (identity,),
            ).fetchone()
            input_rows = connection.execute(
                "SELECT workflow_path,input_json FROM capacity_inputs WHERE run_id=?",
                (identity,),
            ).fetchall()
            if settings_row is None:
                settings = CapacitySettings()
                connection.execute(
                    "INSERT INTO capacity_settings VALUES (?,?)",
                    (identity, settings.model_dump_json()),
                )
            else:
                settings = CapacitySettings.model_validate_json(settings_row["settings_json"])
            persisted = {
                row["workflow_path"]: CapacityWorkflowInput.model_validate_json(row["input_json"])
                for row in input_rows
            }
            missing_rows = [
                (identity, workflow_path, workflow_input.model_dump_json())
                for workflow_path, workflow_input in defaults.items()
                if workflow_path not in persisted
            ]
            if missing_rows:
                connection.executemany(
                    "INSERT INTO capacity_inputs VALUES (?,?,?)",
                    missing_rows,
                )
        return estimate_capacity(
            run.result.assessments,
            {
                path: persisted.get(path, workflow_input)
                for path, workflow_input in defaults.items()
            },
            settings,
        )

    def update_capacity(
        self, identity: str, update: CapacityUpdate
    ) -> CapacityPortfolioEstimate:
        """Persist mutable capacity inputs and return the recomputed estimate."""
        run = self.get_run(identity)
        if run.status != "completed" or run.result is None:
            raise ValueError("Complete an assessment before estimating capacity")
        known_paths = {
            assessment.path
            for assessment in run.result.assessments
            if assessment.capacity_profile is not None
        }
        unknown = sorted(
            workflow.workflow_path
            for workflow in update.inputs
            if workflow.workflow_path not in known_paths
        )
        if unknown:
            raise KeyError(f"Unknown capacity workflow: {unknown[0]}")
        with self._connection() as connection:
            if update.settings is not None:
                connection.execute(
                    """INSERT INTO capacity_settings VALUES (?,?)
                    ON CONFLICT(run_id) DO UPDATE SET settings_json=excluded.settings_json""",
                    (identity, update.settings.model_dump_json()),
                )
            if update.inputs:
                connection.executemany(
                    """INSERT INTO capacity_inputs VALUES (?,?,?)
                    ON CONFLICT(run_id,workflow_path)
                    DO UPDATE SET input_json=excluded.input_json""",
                    [
                        (identity, workflow.workflow_path, workflow.model_dump_json())
                        for workflow in update.inputs
                    ],
                )
        return self._estimate_capacity_for_run(identity, run)

    def export_capacity_csv(self, identity: str) -> str:
        """Export the current capacity estimate as CSV."""
        return capacity_csv(self.get_capacity(identity))

    def _parse_item(self, item: WorkflowCandidateResponse) -> EtlPackage:
        key = ir_cache_key(self._source_registry, item)
        cached = self._store.cache_get("ir_cache", key)
        if cached is not None:
            return EtlPackage.model_validate_json(cached)
        path = Path(item.source_path)
        detected = self._source_registry.detect(path, item.display_path)
        package = self._source_registry.parse(path, detected.match)
        self._store.cache_put("ir_cache", key, package.model_dump_json())
        return package

    def _alteryx_graph(self, item: WorkflowCandidateResponse) -> WorkflowGraph:
        """Parse an Alteryx workflow once for the Fabric engines and seed the IR cache."""
        path = Path(item.source_path)
        adapter = AlteryxSourceAdapter()
        key = ir_cache_key(self._source_registry, item)
        if self._store.cache_has("ir_cache", key):
            return adapter.legacy_graph(path)
        match = adapter.probe(path, item.display_path)
        if match is None:
            return adapter.legacy_graph(path)
        package, graph = adapter.parse_with_graph(path, match)
        self._store.cache_put("ir_cache", key, package.model_dump_json())
        return graph

    def _assess_item(
        self,
        item: WorkflowCandidateResponse,
    ) -> tuple[list[WorkflowAssessmentResponse], str | None, int]:
        key = assessment_cache_key(self._source_registry, item)
        cached = self._store.cache_get("cache", key)
        try:
            if cached is not None:
                cached_value = json.loads(cached)
                assessments = (
                    ASSESSMENT_LIST.validate_python(cached_value)
                    if isinstance(cached_value, list)
                    else [WorkflowAssessmentResponse.model_validate(cached_value)]
                )
                return assessments, None, 1
            path = Path(item.source_path)
            if item.source_platform is SourcePlatform.ALTERYX:
                graph = self._alteryx_graph(item)
                assessments = [
                    WorkflowAssessmentResponse.model_validate(
                        replace(assess_workflow(path, graph=graph), path=item.display_path)
                    )
                ]
            else:
                parsed = self._parse_item(item)
                assessments = [
                    assessment_response(
                        item.display_path,
                        assessment,
                        capacity_profile=build_informatica_capacity_profile(parsed, asset),
                    )
                    for asset, assessment in zip(
                        parsed.assets,
                        assess_package(parsed),
                        strict=True,
                    )
                ]
            self._store.cache_put(
                "cache",
                key,
                json.dumps([assessment.model_dump(mode="json") for assessment in assessments]),
            )
            return assessments, None, 0
        except (WorkflowParseError, ValueError, json.JSONDecodeError) as error:
            return [], f"{item.display_path}: {redact(str(error))}", 0
        except (sqlite3.Error, OSError):
            raise
        except Exception as error:  # noqa: BLE001 - one workflow's fault must not fail the run
            return [], _unexpected_failure(item, error), 0

    def _assess_neutral_item(
        self,
        item: WorkflowCandidateResponse,
    ) -> tuple[list[NeutralAssessmentResponse], str | None]:
        key = neutral_cache_key(item)
        cached = self._store.cache_get("cache", key)
        try:
            if cached is not None:
                return NEUTRAL_LIST.validate_json(cached), None
            parsed = self._parse_item(item)
            neutral = neutral_assessment_responses(parsed, item.display_path)
            self._store.cache_put("cache", key, NEUTRAL_LIST.dump_json(neutral).decode("utf-8"))
            return neutral, None
        except (WorkflowParseError, ValueError, json.JSONDecodeError) as error:
            return [], f"{item.display_path}: {redact(str(error))}"
        except (sqlite3.Error, OSError):
            raise
        except Exception as error:  # noqa: BLE001 - one workflow's fault must not fail the run
            return [], _unexpected_failure(item, error)

    def _assess_item_with_neutral(
        self, item: WorkflowCandidateResponse
    ) -> tuple[
        list[WorkflowAssessmentResponse],
        str | None,
        int,
        list[NeutralAssessmentResponse],
        str | None,
    ]:
        assessments, failure, hit = self._assess_item(item)
        neutral, neutral_failure = self._assess_neutral_item(item)
        return assessments, failure, hit, neutral, neutral_failure

    def generate(self, identity: str, target: Target) -> list[Candidate]:
        run = self.get_run(identity, include_result=False)
        if run.status != "completed":
            raise ValueError("Complete an assessment before generating candidates")
        return self._generate_targets(self._snapshot(run.snapshot_id), (target,))[target]

    def _generate_targets(
        self,
        snapshot: SnapshotPreview,
        targets: tuple[Target, ...],
        renew: Callable[[], bool] | None = None,
    ) -> dict[Target, list[Candidate]]:
        """Parse each workflow once and compile every requested target from that parse.

        One workflow's unexpected fault becomes a blocked candidate. Disk, database,
        and ValueError contract failures still abort the estate: a partial write is
        not a successful one, and an unsupported source is a caller-visible rejection.
        """
        generated: dict[Target, list[Candidate]] = {target: [] for target in targets}
        for item in snapshot.workflows:
            if renew is not None and not renew():
                raise _LeaseLost()
            local: dict[Target, list[Candidate]] = {target: [] for target in targets}
            try:
                self._generate_item(item, targets, local)
            except (OSError, sqlite3.Error, ValueError, _LeaseLost):
                raise
            except Exception as error:  # one workflow must not abort the estate
                message = (
                    f"unexpected generation fault: {item.display_path}: "
                    f"{redact(fault_detail(error))}"
                )
                logger.error(
                    "Unexpected generation fault for %s", item.display_path, exc_info=error
                )
                for target in targets:
                    generated[target].append(
                        _blocked_generation_candidate(item, target, message)
                    )
                continue
            for target in targets:
                generated[target].extend(local[target])
        return generated

    def _generate_item(
        self,
        item: WorkflowCandidateResponse,
        targets: tuple[Target, ...],
        generated: dict[Target, list[Candidate]],
    ) -> None:
        if item.source_platform is SourcePlatform.ALTERYX:
            self._generate_alteryx_item(item, targets, generated)
            return
        package = self._parse_item(item)
        for asset in package.assets:
            for target in targets:
                generated[target].append(
                    self._cached_informatica_candidate(item, package, asset, target)
                )

    def _generate_alteryx_item(
        self,
        item: WorkflowCandidateResponse,
        targets: tuple[Target, ...],
        generated: dict[Target, list[Candidate]],
    ) -> None:
        path = Path(item.source_path)
        pending: list[tuple[Target, str]] = []
        for target in targets:
            key = candidate_cache_key(
                source_sha256=item.sha256,
                display_path=item.display_path,
                platform=str(item.source_platform),
                target=target,
                asset_id=item.display_path,
            )
            cached = self._read_cached_candidate(key)
            if cached is not None:
                generated[target].append(cached)
            else:
                pending.append((target, key))
        if not pending:
            return
        try:
            graph: WorkflowGraph | None = AlteryxSourceAdapter().legacy_graph(path)
        except WorkflowParseError:
            graph = None
        for target, key in pending:
            candidate = generate_candidate(path, target, graph=graph).model_copy(
                update={"workflow": item.display_path}
            )
            self._store_cached_candidate(key, candidate)
            generated[target].append(candidate)

    def _cached_informatica_candidate(
        self,
        item: WorkflowCandidateResponse,
        package: EtlPackage,
        asset: EtlAsset,
        target: Target,
    ) -> Candidate:
        key = candidate_cache_key(
            source_sha256=item.sha256,
            display_path=item.display_path,
            platform=str(item.source_platform),
            target=target,
            asset_id=asset.native_id,
        )
        cached = self._read_cached_candidate(key)
        if cached is not None:
            return cached
        candidate = _informatica_candidate(item.display_path, package, asset, target)
        self._store_cached_candidate(key, candidate)
        return candidate

    def _read_cached_candidate(self, key: str) -> Candidate | None:
        cached = self._store.cache_get("cache", key)
        if cached is None:
            return None
        try:
            return Candidate.model_validate_json(cached)
        except ValidationError:
            return None

    def _store_cached_candidate(self, key: str, candidate: Candidate) -> None:
        self._store.cache_put("cache", key, candidate.model_dump_json())
        self._store.cache_put(
            "cache",
            "artifact:" + key,
            project_candidate(candidate).model_dump_json(),
        )

    def workflow_candidates(
        self, identity: str, workflow_index: int, target: Target
    ) -> list[Candidate]:
        """Return one workflow's candidates from the cache, without writing an artifact tree."""
        run = self.get_run(identity, include_result=False)
        if run.status != "completed":
            raise ValueError("Complete an assessment before generating candidates")
        snapshot = self._snapshot(run.snapshot_id)
        if not 0 <= workflow_index < len(snapshot.workflows):
            raise KeyError("Workflow index not found")
        narrowed = snapshot.model_copy(update={"workflows": [snapshot.workflows[workflow_index]]})
        return self._generate_targets(narrowed, (target,))[target]

    def create_generation_job(self, identity: str, target: Target) -> GenerationJob:
        """Queue generation. The synchronous generate and preview routes stay unchanged."""
        run = self.get_run(identity, include_result=False)
        if run.status != "completed":
            raise ValueError("Complete an assessment before generating candidates")
        job_id = uuid.uuid4().hex
        now = time.time()
        with self._connection() as connection:
            connection.execute(
                """INSERT INTO generation_jobs
                (id, run_id, target, status, created_at) VALUES (?, ?, ?, 'queued', ?)""",
                (job_id, identity, target, now),
            )
        return GenerationJob(id=job_id, run_id=identity, target=target, status="queued")

    def generation_jobs(self, identity: str) -> list[GenerationJob]:
        self.get_run(identity, include_result=False)
        with self._connection() as connection:
            rows = connection.execute(
                """SELECT id, run_id, target, status, attempts, error, result
                FROM generation_jobs WHERE run_id=? ORDER BY created_at, id""",
                (identity,),
            ).fetchall()
        return [_generation_job(row) for row in rows]

    def pending_generation_jobs(self) -> list[str]:
        with self._connection() as connection:
            return [
                row["id"]
                for row in connection.execute(
                    """SELECT id FROM generation_jobs
                    WHERE status='queued' OR (status='running' AND lease<?)""",
                    (time.time(),),
                )
            ]

    def execute_generation_job(self, job_id: str) -> None:
        """Compute and cache candidates. This must not call the artifact writer."""
        claimed = self._claim_generation_job(job_id)
        if claimed is None:
            return
        run_id, target, epoch = claimed
        try:
            run = self.get_run(run_id, include_result=False)
            if run.status != "completed":
                raise ValueError("Complete an assessment before generating candidates")
            snapshot = self._snapshot(run.snapshot_id)
            generated = self._generate_targets(
                snapshot,
                (target,),
                renew=lambda: self._renew_generation_lease(job_id, epoch),
            )
            if not self._renew_generation_lease(job_id, epoch):
                return
            payload = TypeAdapter(list[Candidate]).dump_json(generated[target]).decode()
            with self._connection() as connection:
                connection.execute(
                    """UPDATE generation_jobs SET status='completed', result=?, error=NULL, lease=0
                    WHERE id=? AND epoch=? AND status='running'""",
                    (payload, job_id, epoch),
                )
        except _LeaseLost:
            return
        except Exception as error:
            expected = isinstance(error, OSError | ValueError | KeyError | sqlite3.Error)
            if not expected:
                logger.exception("Generation job %s failed unexpectedly", job_id)
            with self._connection() as connection:
                connection.execute(
                    """UPDATE generation_jobs SET status='failed', error=?, lease=0
                    WHERE id=? AND epoch=? AND status='running'""",
                    (
                        redact(str(error) if expected else f"Unexpected {fault_detail(error)}"),
                        job_id,
                        epoch,
                    ),
                )

    def _claim_generation_job(self, job_id: str) -> tuple[str, Target, int] | None:
        with self._connection() as connection:
            connection.execute("BEGIN IMMEDIATE")
            now = time.time()
            claimable = connection.execute(
                """SELECT run_id, target, attempts FROM generation_jobs
                WHERE id=? AND (status='queued' OR (status='running' AND lease<?))""",
                (job_id, now),
            ).fetchone()
            if claimable is None:
                return None
            if claimable["attempts"] >= MAX_RUN_ATTEMPTS:
                connection.execute(
                    """UPDATE generation_jobs SET status='failed', error=?, lease=0 WHERE id=?""",
                    (
                        f"Generation job abandoned after {MAX_RUN_ATTEMPTS} interrupted attempts",
                        job_id,
                    ),
                )
                return None
            connection.execute(
                """UPDATE generation_jobs
                SET status='running', epoch=epoch+1, attempts=attempts+1, lease=?
                WHERE id=?""",
                (now + LEASE_SECONDS, job_id),
            )
            epoch = int(
                connection.execute(
                    "SELECT epoch FROM generation_jobs WHERE id=?", (job_id,)
                ).fetchone()["epoch"]
            )
            target = claimable["target"]
            if target not in {"notebook", "dataflow", "pipeline"}:
                raise ValueError(f"Unsupported generation target {target!r}")
            return claimable["run_id"], target, epoch

    def _renew_generation_lease(self, job_id: str, epoch: int) -> bool:
        with self._connection() as connection:
            updated = connection.execute(
                """UPDATE generation_jobs SET lease=?
                WHERE id=? AND epoch=? AND status='running'""",
                (time.time() + LEASE_SECONDS, job_id, epoch),
            ).rowcount
        return bool(updated)

    def evaluate_target(
        self, identity: str, platform_id: str, registry: TargetPlatformRegistry
    ) -> list[RunTargetEvaluation]:
        """Evaluate confirmed source assets with a registered target provider.

        This is the target-fit stage that follows portfolio assessment. For Fabric on
        built-in sources it confirms every static assessment with the compilers and
        stores the result for ``get_run`` to apply. It always reads the stored static
        assessment, never the confirmed view, so repeating it gives the same answer.
        """
        run, basis = self._read_run(identity, include_result=True)
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
        evaluations: list[RunTargetEvaluation] = []
        for item in self._snapshot(run.snapshot_id).workflows:
            evaluations.extend(self._evaluate_item(item, provider, registry, static, key))
        with self._connection() as connection:
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
        """Evaluate the assets of one workflow.

        With ``key`` set, this confirms the stored static assessments of a built-in
        source: Alteryx through the provider's staged-path evaluator, because Alteryx
        generation reads the legacy workflow graph, and other sources through canonical IR.
        Without it, assets are evaluated generically from canonical IR.
        """
        built_in = isinstance(item.source_platform, SourcePlatform)
        try:
            package = self._parse_item(item)
        except (WorkflowParseError, ValueError):
            if key is not None and built_in:
                return []  # Assessment already failed this workflow; there is nothing to confirm.
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

    def generate_for_target(
        self,
        identity: str,
        platform_id: str,
        target_kind: str,
        registry: TargetPlatformRegistry,
    ) -> list[TargetGenerationResult]:
        """Generate target-neutral artifact previews via TargetCodeGeneratorProvider."""
        run = self.get_run(identity, include_result=False)
        if run.status != "completed":
            raise ValueError("Complete an assessment before generating target previews")
        results: list[TargetGenerationResult] = []
        for item in self._snapshot(run.snapshot_id).workflows:
            package = self._parse_item(item)
            results.append(
                registry.generate_package(
                    platform_id,
                    package,
                    target_kind=target_kind,
                    display_path=item.display_path,
                )
            )
        return results

    def estimate_target_capacity(
        self,
        identity: str,
        platform_id: str,
        registry: TargetPlatformRegistry,
    ) -> list[TargetCapacityResult]:
        """Estimate capacity for confirmed assets via a registered TargetCapacityProvider."""
        run = self.get_run(identity, include_result=False)
        if run.status != "completed":
            raise ValueError("Complete an assessment before estimating target capacity")
        results: list[TargetCapacityResult] = []
        for item in self._snapshot(run.snapshot_id).workflows:
            package = self._parse_item(item)
            results.append(registry.estimate_capacity(platform_id, package))
        return results

    def assess_neutral(self, identity: str) -> NeutralEstateAssessmentResponse:
        """Assess the confirmed run snapshot without target-specific routing."""
        run = self.get_run(identity, include_result=False)
        if run.status != "completed":
            raise ValueError("Complete an assessment before building a neutral baseline")
        snapshot = self._snapshot(run.snapshot_id)
        assessments: list[NeutralAssessmentResponse] = []
        failures: list[str] = []
        for item in snapshot.workflows:
            item_assessments, failure = self._assess_neutral_item(item)
            assessments.extend(item_assessments)
            if failure is not None:
                failures.append(failure)
        result = _neutral_estate(snapshot, assessments, failures)
        with self._connection() as connection:
            connection.execute(
                """INSERT INTO neutral_assessments (run_id, assessment_json) VALUES (?, ?)
                ON CONFLICT(run_id) DO UPDATE SET assessment_json=excluded.assessment_json""",
                (identity, result.model_dump_json()),
            )
        return result

    def get_neutral_assessment(self, identity: str) -> NeutralEstateAssessmentResponse:
        """Return the saved neutral baseline for a run."""
        self.get_run(identity, include_result=False)
        with self._connection() as connection:
            row = connection.execute(
                "SELECT assessment_json FROM neutral_assessments WHERE run_id=?", (identity,)
            ).fetchone()
        if row is None:
            raise KeyError("No neutral baseline exists for this run")
        return NeutralEstateAssessmentResponse.model_validate_json(row["assessment_json"])

    def get_target_evaluations(
        self, identity: str, platform_id: str
    ) -> list[RunTargetEvaluation]:
        """Return the last completed evaluation for one run and target."""
        self.get_run(identity, include_result=False)
        with self._connection() as connection:
            row = connection.execute(
                "SELECT evaluations_json FROM target_evaluations WHERE run_id=? AND platform_id=?",
                (identity, platform_id.strip().casefold()),
            ).fetchone()
        if row is None:
            raise KeyError("No saved evaluation exists for this run and target")
        return TARGET_EVALUATION_LIST.validate_json(row["evaluations_json"])

    def export_csv(self, identity: str) -> str:
        run = self.get_run(identity)
        if run.result is None:
            raise ValueError("Run has no assessment results")
        output = io.StringIO()
        writer = csv.writer(output)
        writer.writerow(["Workflow", "Tools", "Complexity", "Target", "Remaining effort days"])
        for item in run.result.assessments:
            name = redact(item.path)
            if name.startswith(("\t", "\r")) or name.lstrip().startswith(("=", "+", "-", "@")):
                name = "'" + name
            writer.writerow(
                [
                    name,
                    item.tool_count,
                    item.complexity_score,
                    item.recommended_target,
                    item.estimated_effort_days,
                ]
            )
        return output.getvalue()

    def candidate_package(self, identity: str, target: Target) -> bytes:
        """Build a byte-stable archive from an isolated set of Fabric definitions."""
        with tempfile.TemporaryDirectory(prefix="candidate-package-", dir=self.root) as directory:
            persisted = self._write_artifacts(
                identity, (target,), artifact_root=Path(directory), write_plan=False
            )[target]
            return build_candidate_package(persisted, target)

    def preview_candidates(self, identity: str, target: Target) -> list[Candidate]:
        """Generate candidate previews without changing the shared artifact directory."""
        with tempfile.TemporaryDirectory(prefix="candidate-preview-", dir=self.root) as directory:
            return self._write_artifacts(
                identity, (target,), artifact_root=Path(directory), write_plan=False
            )[target].candidates

    def workflow_package(self, identity: str, workflow: str) -> tuple[bytes, str]:
        """Build a byte-stable archive for one workflow and all generated items."""
        with tempfile.TemporaryDirectory(prefix="workflow-package-", dir=self.root) as directory:
            root = Path(directory)
            results = self._write_artifacts(
                identity, ("dataflow", "notebook", "pipeline"), artifact_root=root
            )
            candidates = [
                candidate for result in results.values() for candidate in result.candidates
            ]
            return build_workflow_package(
                artifact_root=root,
                candidates=candidates,
                workflow=workflow,
            )

    def write_artifacts(self, identity: str, target: Target) -> ArtifactWriteResult:
        """Persist both targets together below generated-fabric-workflows/<workflow>."""
        return self._write_artifacts(identity, (target,))[target]

    def write_all_artifacts(self, identity: str) -> dict[Target, ArtifactWriteResult]:
        """Persist each target while sharing generated candidates across plans."""
        return self._write_artifacts(identity, ("dataflow", "notebook", "pipeline"))

    @contextmanager
    def stage_all_artifacts(
        self, identity: str
    ) -> Iterator[dict[Target, ArtifactWriteResult]]:
        """Stage all targets for the lifetime of an isolated deployment plan."""
        with tempfile.TemporaryDirectory(prefix="deployment-plan-", dir=self.root) as directory:
            yield self._write_artifacts(
                identity,
                ("dataflow", "notebook", "pipeline"),
                artifact_root=Path(directory),
            )

    def publish_artifacts(self, identity: str) -> ArtifactPublication:
        """Publish all targets atomically to a run-scoped content-addressed directory."""
        if not re.fullmatch(r"[a-f0-9]{32}", identity):
            raise ValueError("Run ID must be a 32-character lowercase hexadecimal value")
        run = self.get_run(identity, include_result=False)
        if run.status != "completed":
            raise ValueError("Complete an assessment before publishing artifacts")
        publications = self.root / "publications"
        parent = publications / identity
        for directory in (publications, parent):
            if directory.is_symlink() or directory.is_junction():
                raise ValueError("Artifact publication contains a linked path")
            directory.mkdir(exist_ok=True)
        with tempfile.TemporaryDirectory(prefix=".staging-", dir=parent) as temporary:
            staging = Path(temporary) / "contents"
            self._write_artifacts(
                identity, ("dataflow", "notebook", "pipeline"), artifact_root=staging
            )
            manifest = build_manifest(staging, identity)
            digest = manifest_digest(manifest)
            (staging / MANIFEST_NAME).write_bytes(manifest_bytes(manifest))
            destination = parent / digest
            try:
                staging.rename(destination)
            except OSError:
                if not destination.is_dir():
                    raise
                check_tree(destination, manifest)
            return ArtifactPublication(run_id=identity, digest=digest, root=destination.resolve())

    def verify_publication(self, identity: str, digest: str) -> ArtifactPublication:
        """Verify a local publication's manifest and every listed artifact."""
        if not re.fullmatch(r"[a-f0-9]{32}", identity):
            raise ValueError("Run ID must be a 32-character lowercase hexadecimal value")
        if not re.fullmatch(r"[a-f0-9]{64}", digest):
            raise ValueError(
                "Publication digest must be a 64-character lowercase hexadecimal value"
            )
        self.get_run(identity, include_result=False)
        publications = self.root / "publications"
        parent = publications / identity
        root = parent / digest
        if any(path.is_symlink() or path.is_junction() for path in (publications, parent, root)):
            raise ValueError("Artifact publication contains a linked path")
        manifest = read_manifest(root)
        if manifest.get("run_id") != identity or manifest_digest(manifest) != digest:
            raise ValueError("Artifact publication manifest does not match its identity")
        check_tree(root, manifest)
        return ArtifactPublication(run_id=identity, digest=digest, root=root.resolve())

    def verify_staged_publication(
        self, identity: str, digest: str, staged_root: Path
    ) -> str:
        """Check regenerated artifacts against a publication and return its manifest byte hash."""
        publication = self.verify_publication(identity, digest)
        staged = build_manifest(staged_root, identity)
        if manifest_digest(staged) != digest:
            raise ValueError("Current artifacts do not match the selected publication")
        try:
            content = (publication.root / MANIFEST_NAME).read_bytes()
            recorded = json.loads(content)
        except (OSError, UnicodeDecodeError, json.JSONDecodeError) as error:
            raise ValueError("Artifact publication manifest is unavailable or invalid") from error
        if not isinstance(recorded, dict) or manifest_digest(recorded) != digest:
            raise ValueError("Artifact publication manifest does not match its identity")
        check_tree(publication.root, recorded)
        return hashlib.sha256(content).hexdigest()

    def publication_package(self, identity: str, digest: str) -> bytes:
        """Package only verified publication manifest entries in a deterministic ZIP."""
        publication = self.verify_publication(identity, digest)
        manifest = build_manifest(publication.root, identity)
        check_tree(publication.root, manifest)
        if manifest_digest(manifest) != digest:
            raise ValueError("Artifact publication has changed while packaging")
        return build_archive(publication.root, manifest)

    def _write_artifacts(
        self,
        identity: str,
        targets: tuple[Target, ...],
        *,
        artifact_root: Path | None = None,
        write_plan: bool = True,
    ) -> dict[Target, ArtifactWriteResult]:
        if not re.fullmatch(r"[a-f0-9]{32}", identity):
            raise ValueError("Run ID must be a 32-character lowercase hexadecimal value")
        run = self.ensure_fabric_fit(identity)
        if run.status != "completed":
            raise ValueError("Complete an assessment before generating candidates")
        needed = tuple(dict.fromkeys((*targets, *(ALL_TARGETS if write_plan else ()))))
        generated = self._generate_targets(self._snapshot(run.snapshot_id), needed)
        return {
            target: write_candidates(
                run_id=identity,
                target=target,
                artifact_root=artifact_root if artifact_root is not None else self.artifact_root,
                generate_fn=generated.__getitem__,
                assessments=run.result.assessments if run.result else [],
                write_plan=write_plan,
            )
            for target in targets
        }

    def evidence(self, identity: str, workflow_index: int | None = None) -> EvidenceResponse:
        run = self.get_run(identity, include_result=False)
        if run.status != "completed":
            raise ValueError("Complete the assessment before inspecting evidence")
        snapshot = self._snapshot(run.snapshot_id)
        if workflow_index is not None and not 0 <= workflow_index < len(snapshot.workflows):
            raise KeyError("Workflow index not found")
        indices = (
            [workflow_index]
            if workflow_index is not None
            else list(range(min(len(snapshot.workflows), 100)))
        )
        workflows = []
        nodes = 0
        size = 0
        for index in indices:
            if nodes >= 10_000:
                break
            item = snapshot.workflows[index]
            if item.source_platform is SourcePlatform.ALTERYX:
                asset_evidence = [
                    workflow_evidence(
                        Path(item.source_path),
                        item.display_path,
                        index,
                        support_classifier=alteryx_support_for,
                    )
                ]
            else:
                package = self._parse_item(item)
                asset_evidence = [
                    etl_asset_evidence(
                        package,
                        asset,
                        item.display_path,
                        index,
                        support_classifier=etl_support_for,
                    )
                    for asset in package.assets
                ]
            for evidence in asset_evidence:
                if evidence.source_sha256 and evidence.source_sha256 != item.sha256:
                    raise ValueError("Confirmed workflow changed; review the selection again")
                size += len(evidence.model_dump_json().encode("utf-8"))
                if size > 3 * 1024 * 1024:
                    if workflow_index is not None:
                        raise ValueError("Workflow evidence exceeds the view limit")
                    break
                workflows.append(evidence)
                nodes += len(evidence.nodes)
        response = EvidenceResponse(
            run_id=identity,
            snapshot_id=run.snapshot_id,
            total_workflows=len(snapshot.workflows),
            workflows=workflows,
            truncated=len(workflows)
            < (1 if workflow_index is not None else len(snapshot.workflows)),
        )
        if len(response.model_dump_json()) > 4 * 1024 * 1024:
            raise ValueError("Evidence exceeds the view limit; inspect one workflow at a time")
        return response


def _neutral_estate(
    snapshot: SnapshotPreview,
    assessments: list[NeutralAssessmentResponse],
    failures: list[str],
) -> NeutralEstateAssessmentResponse:
    return NeutralEstateAssessmentResponse(
        workflow_count=len(assessments),
        failed_count=len(failures),
        assessments=assessments,
        failures=failures,
        workflows=[
            NeutralWorkflowCandidateResponse.model_validate(item.model_dump())
            for item in snapshot.workflows
        ],
        skipped=[
            NeutralSkippedItemResponse.model_validate(item.model_dump())
            for item in snapshot.skipped
        ],
    )


def _informatica_candidate(
    display_path: str,
    package: EtlPackage,
    asset: EtlAsset,
    target: Target,
    *,
    compiled: EtlCompiledCandidate | None = None,
) -> Candidate:
    if not isinstance(package.source_platform, SourcePlatform):
        raise ValueError(f"Fabric generation does not support source {package.source_platform!r}")
    compiled_result = compiled or compile_asset(package, asset, target)
    asset_path = "/".join(part for part in (asset.folder, asset.name) if part)
    workflow = f"{display_path}!{asset_path}" if asset_path else display_path
    code = compiled_result.code
    return Candidate(
        workflow=workflow,
        target=target,
        validation_state=compiled_result.validation_state,
        translation_mode=(
            "native" if compiled_result.validation_state == "generated_unvalidated" else "scaffold"
        ),
        deployable=compiled_result.deployable,
        definition_ready=compiled_result.deployable,
        runtime_ready=compiled_result.runtime_ready,
        source_sha256=package.source_sha256 or hashlib.sha256(display_path.encode()).hexdigest(),
        code_sha256=hashlib.sha256(code.encode()).hexdigest(),
        graph_version=IR_VERSION,
        registry_version=REGISTRY_VERSIONS[package.source_platform],
        rules_version=ASSESSMENT_RULES_VERSION,
        compiler_version=ETL_COMPILER_VERSION,
        code=code,
        diagnostics=list(compiled_result.diagnostics),
        required_bindings=list(compiled_result.required_bindings),
        definition_queries=list(compiled_result.definition_queries),
        loaded_queries=list(compiled_result.loaded_outputs),
        source_platform=package.source_platform,
        source_product=package.source_product,
        asset_type=asset.asset_type,
        native_id=asset.native_id,
        folder=asset.folder,
    )
