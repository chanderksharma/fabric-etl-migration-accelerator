"""Immutable local snapshots, durable jobs, and context-keyed incremental results."""

import csv
import hashlib
import io
import json
import re
import sqlite3
import tempfile
import time
import uuid
from collections.abc import Iterable, Iterator
from concurrent.futures import ThreadPoolExecutor, wait
from contextlib import contextmanager
from dataclasses import replace
from pathlib import Path
from threading import RLock
from typing import Literal, Self

from pydantic import BaseModel, TypeAdapter

from etl_migration_core.contracts.ir import IR_VERSION, EtlAsset, EtlPackage, SourcePlatform
from etl_migration_core.intake.discovery import DiscoveryService
from etl_migration_core.intake.domain import WorkflowCandidate
from etl_migration_core.sources.alteryx.graph import GRAPH_VERSION, WorkflowParseError, redact
from etl_migration_core.sources.defaults import create_default_registry
from etl_portfolio_assessment.evidence.extractor import (
    EvidenceResponse,
    etl_asset_evidence,
    workflow_evidence,
)
from etl_target_fabric.assessment.evaluator import apply_alteryx_native_route, apply_native_route
from etl_target_fabric.assessment.ir_assessment import (
    ASSESSMENT_RULES_VERSION,
    REGISTRY_VERSIONS,
    assess_package,
)
from etl_target_fabric.assessment.portfolio import assessment_response
from etl_target_fabric.assessment.schemas import (
    DiscoverySummaryResponse,
    EstateAssessmentResponse,
    SkippedItemResponse,
    WorkflowAssessmentResponse,
    WorkflowCandidateResponse,
)
from etl_target_fabric.assessment.support_matrix import alteryx_support_for, etl_support_for
from etl_target_fabric.assessment.workflow import (
    REGISTRY_VERSION,
    RULES_VERSION,
    assess_workflow,
)
from etl_target_fabric.capacity.model import (
    CAPACITY_MODEL_VERSION,
    CapacityPortfolioEstimate,
    CapacitySettings,
    CapacityUpdate,
    CapacityWorkflowInput,
    build_informatica_capacity_profile,
    capacity_csv,
    estimate_capacity,
)
from etl_target_fabric.compilers.alteryx import (
    COMPILER_VERSION,
    Candidate,
    Target,
    generate_candidate,
)
from etl_target_fabric.compilers.ir import (
    ETL_COMPILER_VERSION,
    compile_asset,
)
from etl_target_fabric.delivery.artifact_writer import (
    ArtifactWriteResult,
    _artifact_path,
    build_candidate_package,
    build_workflow_package,
    write_candidates,
)

ASSESSMENT_LIST = TypeAdapter(list[WorkflowAssessmentResponse])
LEASE_SECONDS = 300
LEASE_RENEWAL_INTERVAL_SECONDS = 60
WORKER_POLL_SECONDS = 5
COPY_BUFFER_BYTES = 1024 * 1024


def _snapshot_id(
    workflows: Iterable[WorkflowCandidate | WorkflowCandidateResponse],
) -> str:
    identity = json.dumps(
        {
            "files": [
                (
                    item.display_path,
                    item.sha256,
                    item.source_platform,
                    item.adapter_version,
                )
                for item in workflows
            ],
            "versions": [
                GRAPH_VERSION,
                REGISTRY_VERSION,
                RULES_VERSION,
                IR_VERSION,
            ],
        },
        sort_keys=True,
    )
    return hashlib.sha256(identity.encode()).hexdigest()


def _sha256_file(path: Path) -> str:
    with path.open("rb") as stream:
        return hashlib.file_digest(stream, "sha256").hexdigest()


def _copy_with_sha256(source: Path, destination: Path) -> str:
    digest = hashlib.sha256()
    with source.open("rb") as input_stream, destination.open("wb") as output_stream:
        while chunk := input_stream.read(COPY_BUFFER_BYTES):
            output_stream.write(chunk)
            digest.update(chunk)
    return digest.hexdigest()


__all__ = ["ArtifactWriteResult", "Run", "RunService", "SnapshotPreview", "_artifact_path"]


class SnapshotPreview(DiscoverySummaryResponse):
    snapshot_id: str


class Run(BaseModel):
    id: str
    snapshot_id: str
    status: Literal["queued", "running", "completed", "failed", "cancelled"]
    processed: int
    total: int
    cache_hits: int
    error: str | None = None
    result: EstateAssessmentResponse | None = None


class RunService:
    """Single-host WAL store with atomic work claims and commit fencing."""

    def __init__(self, root: Path, artifact_root: Path | None = None) -> None:
        self.root = root
        self.artifact_root = artifact_root or root.parent / "generated-fabric-workflows"
        self._discovery = DiscoveryService()
        self._source_registry = create_default_registry()
        root.mkdir(parents=True, exist_ok=True)
        self.database = root / "runs.db"
        self._lock = RLock()
        self.closed = False
        with self._connection() as connection:
            connection.execute("PRAGMA journal_mode=WAL")
            version = connection.execute("PRAGMA user_version").fetchone()[0]
            if version not in {0, 1, 2}:
                raise ValueError("Unsupported run database schema version")
            connection.executescript(
                """
                CREATE TABLE IF NOT EXISTS snapshots (id TEXT PRIMARY KEY, preview TEXT NOT NULL);
                CREATE TABLE IF NOT EXISTS runs (
                    id TEXT PRIMARY KEY, snapshot TEXT NOT NULL, status TEXT NOT NULL,
                    epoch INTEGER NOT NULL DEFAULT 0, lease REAL NOT NULL DEFAULT 0,
                    processed INTEGER NOT NULL DEFAULT 0, total INTEGER NOT NULL,
                    cache_hits INTEGER NOT NULL DEFAULT 0, error TEXT, result TEXT
                );
                CREATE TABLE IF NOT EXISTS cache (key TEXT PRIMARY KEY, result TEXT NOT NULL);
                CREATE TABLE IF NOT EXISTS capacity_inputs (
                    run_id TEXT NOT NULL,
                    workflow_path TEXT NOT NULL,
                    input_json TEXT NOT NULL,
                    PRIMARY KEY (run_id, workflow_path)
                );
                CREATE TABLE IF NOT EXISTS capacity_settings (
                    run_id TEXT PRIMARY KEY,
                    settings_json TEXT NOT NULL
                );
                PRAGMA user_version=2;
                """
            )

    @contextmanager
    def _connection(self) -> Iterator[sqlite3.Connection]:
        with self._lock:
            if self.closed:
                raise ValueError("Run store is closed")
            connection = sqlite3.connect(self.database, timeout=30)
            connection.row_factory = sqlite3.Row
            try:
                with connection:
                    yield connection
            finally:
                connection.close()

    def __enter__(self) -> Self:
        if self.closed:
            raise ValueError("Run store is closed")
        return self

    def __exit__(self, *_error: object) -> None:
        self.close()

    def close(self) -> None:
        with self._lock:
            self.closed = True

    def preview(self, source: Path) -> SnapshotPreview:
        summary = self._discovery.discover(source)
        snapshot_id = _snapshot_id(summary.workflows)
        folder = self.root / "snapshots" / snapshot_id
        folder.mkdir(parents=True, exist_ok=True)
        files: list[WorkflowCandidateResponse] = []
        for index, candidate in enumerate(summary.workflows):
            destination = folder / f"{index}{candidate.extension}"
            if not destination.exists():
                with tempfile.NamedTemporaryFile(dir=folder, delete=False) as temporary:
                    staging = Path(temporary.name)
                try:
                    with self._discovery.staged_workflow(candidate) as original:
                        staged_sha256 = _copy_with_sha256(original, staging)
                    if staged_sha256 != candidate.sha256:
                        raise ValueError(
                            "Source changed during preview; review the selection again"
                        )
                    staging.replace(destination)
                finally:
                    staging.unlink(missing_ok=True)
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
                "INSERT OR REPLACE INTO snapshots VALUES (?, ?)",
                (snapshot_id, preview.model_dump_json()),
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
            if _sha256_file(Path(item.source_path)) != item.sha256:
                raise ValueError("Confirmed snapshot changed; review the selection again")
        return preview

    def create_run(self, snapshot_id: str) -> Run:
        preview = self._snapshot(snapshot_id)
        if not preview.workflows:
            raise ValueError("No supported workflows were found; select a different input")
        identity = uuid.uuid4().hex
        with self._connection() as connection:
            connection.execute(
                "INSERT INTO runs (id,snapshot,status,total) VALUES (?,?,'queued',?)",
                (identity, snapshot_id, preview.workflow_count),
            )
        return self.get_run(identity)

    def get_run(self, identity: str) -> Run:
        with self._connection() as connection:
            row = connection.execute("SELECT * FROM runs WHERE id=?", (identity,)).fetchone()
        if row is None:
            raise KeyError("Run not found")
        return Run(
            id=row["id"],
            snapshot_id=row["snapshot"],
            status=row["status"],
            processed=row["processed"],
            total=row["total"],
            cache_hits=row["cache_hits"],
            error=row["error"],
            result=EstateAssessmentResponse.model_validate_json(row["result"])
            if row["result"]
            else None,
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
            updated = connection.execute(
                """UPDATE runs SET status='running', epoch=epoch+1, lease=?
                WHERE id=? AND (status='queued' OR (status='running' AND lease<?))""",
                (time.time() + LEASE_SECONDS, identity, time.time()),
            )
            if not updated.rowcount:
                return None
            return int(
                connection.execute("SELECT epoch FROM runs WHERE id=?", (identity,)).fetchone()[
                    "epoch"
                ]
            )

    def execute(self, identity: str) -> None:
        epoch = self._claim(identity)
        if epoch is None:
            return
        run = self.get_run(identity)
        assessments: list[WorkflowAssessmentResponse] = []
        failures: list[str] = []
        hits = 0
        try:
            snapshot = self._snapshot(run.snapshot_id)
            with ThreadPoolExecutor(max_workers=4) as executor:
                for offset in range(0, len(snapshot.workflows), 4):
                    if self.get_run(identity).status != "running":
                        return
                    batch = snapshot.workflows[offset : offset + 4]
                    futures = [executor.submit(self._assess_item, item) for item in batch]
                    remaining = set(futures)
                    while remaining:
                        _, remaining = wait(remaining, timeout=WORKER_POLL_SECONDS)
                        if remaining:
                            with self._connection() as connection:
                                lease_row = connection.execute(
                                    """SELECT lease FROM runs
                                    WHERE id=? AND epoch=? AND status='running'""",
                                    (identity, epoch),
                                ).fetchone()
                                if lease_row is None:
                                    return
                                if lease_row["lease"] <= (
                                    time.time() + LEASE_RENEWAL_INTERVAL_SECONDS
                                ):
                                    renewed = connection.execute(
                                        """UPDATE runs SET lease=?
                                        WHERE id=? AND epoch=? AND status='running'""",
                                        (time.time() + LEASE_SECONDS, identity, epoch),
                                    ).rowcount
                                    if not renewed:
                                        return
                    for future in futures:
                        item_assessments, failure, hit = future.result()
                        hits += hit
                        assessments.extend(item_assessments)
                        if failure is not None:
                            failures.append(failure)
                    with self._connection() as connection:
                        updated = connection.execute(
                            """UPDATE runs SET processed=?, cache_hits=?, lease=?
                            WHERE id=? AND epoch=? AND status='running'""",
                            (
                                offset + len(batch),
                                hits,
                                time.time() + LEASE_SECONDS,
                                identity,
                                epoch,
                            ),
                        )
                        if not updated.rowcount:
                            return
            result = EstateAssessmentResponse(
                workflow_count=len(assessments),
                failed_count=len(failures),
                assessments=assessments,
                failures=failures,
                workflows=snapshot.workflows,
                skipped=snapshot.skipped,
            )
            with self._connection() as connection:
                connection.execute(
                    """UPDATE runs SET status='completed', result=?, lease=0
                    WHERE id=? AND epoch=? AND status='running'""",
                    (result.model_dump_json(), identity, epoch),
                )
        except (OSError, ValueError, KeyError, sqlite3.Error) as error:
            with self._connection() as connection:
                connection.execute(
                    """UPDATE runs SET status='failed',error=?,lease=0
                    WHERE id=? AND epoch=? AND status='running'""",
                    (redact(str(error)), identity, epoch),
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

    def _assess_item(
        self, item: WorkflowCandidateResponse
    ) -> tuple[list[WorkflowAssessmentResponse], str | None, int]:
        key = hashlib.sha256(
            json.dumps(
                [
                    item.sha256,
                    item.display_path,
                    item.source_platform,
                    item.adapter_version,
                    GRAPH_VERSION,
                    REGISTRY_VERSION,
                    RULES_VERSION,
                    ASSESSMENT_RULES_VERSION,
                    COMPILER_VERSION,
                    ETL_COMPILER_VERSION,
                    IR_VERSION,
                    CAPACITY_MODEL_VERSION,
                ],
            ).encode()
        ).hexdigest()
        with self._connection() as connection:
            cached = connection.execute("SELECT result FROM cache WHERE key=?", (key,)).fetchone()
        try:
            if cached:
                cached_value = json.loads(cached["result"])
                assessments = (
                    ASSESSMENT_LIST.validate_python(cached_value)
                    if isinstance(cached_value, list)
                    else [WorkflowAssessmentResponse.model_validate(cached_value)]
                )
                return assessments, None, 1
            path = Path(item.source_path)
            if item.source_platform is SourcePlatform.ALTERYX:
                assessments = [
                    WorkflowAssessmentResponse.model_validate(
                        replace(
                            apply_alteryx_native_route(path, assess_workflow(path)),
                            path=item.display_path,
                        )
                    )
                ]
            else:
                detected = self._source_registry.detect(path, item.display_path)
                package = self._source_registry.parse(path, detected.match)
                assessments = [
                    assessment_response(
                        item.display_path,
                        apply_native_route(package, asset, assessment),
                        capacity_profile=build_informatica_capacity_profile(
                            package, asset
                        ),
                    )
                    for asset, assessment in zip(
                        package.assets,
                        assess_package(package),
                        strict=True,
                    )
                ]
            with self._connection() as connection:
                connection.execute(
                    "INSERT OR REPLACE INTO cache VALUES (?,?)",
                    (
                        key,
                        json.dumps(
                            [
                                assessment.model_dump(mode="json")
                                for assessment in assessments
                            ]
                        ),
                    ),
                )
            return assessments, None, 0
        except (WorkflowParseError, ValueError, json.JSONDecodeError) as error:
            return [], f"{item.display_path}: {redact(str(error))}", 0

    def generate(self, identity: str, target: Target) -> list[Candidate]:
        run = self.get_run(identity)
        if run.status != "completed":
            raise ValueError("Complete an assessment before generating candidates")
        candidates: list[Candidate] = []
        for item in self._snapshot(run.snapshot_id).workflows:
            path = Path(item.source_path)
            if item.source_platform is SourcePlatform.ALTERYX:
                candidates.append(
                    generate_candidate(path, target).model_copy(
                        update={"workflow": item.display_path}
                    )
                )
                continue
            detected = self._source_registry.detect(path, item.display_path)
            package = self._source_registry.parse(path, detected.match)
            candidates.extend(
                _informatica_candidate(item.display_path, package, asset, target)
                for asset in package.assets
            )
        return candidates

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
        """Build a byte-stable archive from the persisted Fabric definitions."""
        persisted = self.write_artifacts(identity, target)
        return build_candidate_package(persisted, target)

    def workflow_package(self, identity: str, workflow: str) -> tuple[bytes, str]:
        """Build a byte-stable archive for one workflow and all generated items."""
        dataflows = self.write_artifacts(identity, "dataflow")
        notebooks = self.write_artifacts(identity, "notebook")
        pipelines = self.write_artifacts(identity, "pipeline")
        candidates = [*dataflows.candidates, *notebooks.candidates, *pipelines.candidates]
        return build_workflow_package(
            artifact_root=self.artifact_root,
            candidates=candidates,
            workflow=workflow,
        )

    def write_artifacts(self, identity: str, target: Target) -> ArtifactWriteResult:
        """Persist both targets together below generated-fabric-workflows/<workflow>."""
        if not re.fullmatch(r"[a-f0-9]{32}", identity):
            raise ValueError("Run ID must be a 32-character lowercase hexadecimal value")
        run = self.get_run(identity)
        return write_candidates(
            run_id=identity,
            target=target,
            artifact_root=self.artifact_root,
            generate_fn=lambda item_target: self.generate(identity, item_target),
            assessments=run.result.assessments if run.result else [],
        )

    def evidence(self, identity: str, workflow_index: int | None = None) -> EvidenceResponse:
        run = self.get_run(identity)
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
                path = Path(item.source_path)
                detected = self._source_registry.detect(path, item.display_path)
                package = self._source_registry.parse(path, detected.match)
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


def _informatica_candidate(
    display_path: str,
    package: EtlPackage,
    asset: EtlAsset,
    target: Target,
) -> Candidate:
    compiled = compile_asset(package, asset, target)
    asset_path = "/".join(part for part in (asset.folder, asset.name) if part)
    workflow = f"{display_path}!{asset_path}" if asset_path else display_path
    code = compiled.code
    return Candidate(
        workflow=workflow,
        target=target,
        validation_state=compiled.validation_state,
        translation_mode=(
            "native" if compiled.validation_state == "generated_unvalidated" else "scaffold"
        ),
        deployable=compiled.deployable,
        definition_ready=compiled.deployable,
        runtime_ready=compiled.runtime_ready,
        source_sha256=package.source_sha256 or hashlib.sha256(display_path.encode()).hexdigest(),
        code_sha256=hashlib.sha256(code.encode()).hexdigest(),
        graph_version=IR_VERSION,
        registry_version=REGISTRY_VERSIONS[package.source_platform],
        rules_version=ASSESSMENT_RULES_VERSION,
        compiler_version=ETL_COMPILER_VERSION,
        code=code,
        diagnostics=list(compiled.diagnostics),
        required_bindings=list(compiled.required_bindings),
        definition_queries=list(compiled.definition_queries),
        loaded_queries=list(compiled.loaded_outputs),
        source_platform=package.source_platform,
        source_product=package.source_product,
        asset_type=asset.asset_type,
        native_id=asset.native_id,
        folder=asset.folder,
    )
