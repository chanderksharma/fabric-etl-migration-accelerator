"""Immutable local snapshots, durable jobs, and context-keyed incremental results."""

import ast
import base64
import csv
import hashlib
import io
import json
import re
import sqlite3
import tempfile
import time
import uuid
import zipfile
from collections.abc import Iterable, Iterator
from concurrent.futures import ThreadPoolExecutor, wait
from contextlib import contextmanager
from dataclasses import dataclass, replace
from pathlib import Path
from threading import RLock
from typing import Literal, Self

from pydantic import BaseModel, TypeAdapter

from accelerator.application import assessment_response
from accelerator.assessment import (
    REGISTRY_VERSION,
    RULES_VERSION,
    WorkflowAssessment,
    assess_workflow,
)
from accelerator.capacity import (
    CAPACITY_MODEL_VERSION,
    CapacityPortfolioEstimate,
    CapacitySettings,
    CapacityUpdate,
    CapacityWorkflowInput,
    build_informatica_capacity_profile,
    capacity_csv,
    estimate_capacity,
)
from accelerator.discovery import DiscoveryService
from accelerator.domain import WorkflowCandidate
from accelerator.effort import remaining_effort_days
from accelerator.etl_assessment import (
    ASSESSMENT_RULES_VERSION,
    REGISTRY_VERSIONS,
    assess_package,
)
from accelerator.etl_generation import (
    ETL_COMPILER_VERSION,
    compile_asset,
)
from accelerator.etl_ir import IR_VERSION, EtlAsset, EtlPackage, SourcePlatform
from accelerator.etl_routing import apply_native_route
from accelerator.evidence import EvidenceResponse, etl_asset_evidence, workflow_evidence
from accelerator.generation import COMPILER_VERSION, Candidate, Target, generate_candidate
from accelerator.graph import GRAPH_VERSION, WorkflowParseError, redact
from accelerator.schemas import (
    DiscoverySummaryResponse,
    EstateAssessmentResponse,
    SkippedItemResponse,
    WorkflowAssessmentResponse,
    WorkflowCandidateResponse,
)
from accelerator.sources.defaults import create_default_registry

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


@dataclass(frozen=True)
class ArtifactWriteResult:
    root: Path
    candidates: list[Candidate]


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


def _apply_native_route(path: Path, assessment: WorkflowAssessment) -> WorkflowAssessment:
    if (
        assessment.unsupported_tools
        and {"Dataflow Gen2", "Fabric Notebook"}.issubset(assessment.target_components)
    ):
        dataflow = generate_candidate(path, "dataflow")
        notebook = generate_candidate(path, "notebook")
        if dataflow.deployable and notebook.deployable:
            bindings = (*dataflow.required_bindings, *notebook.required_bindings)
            return replace(
                assessment,
                recommended_target="Mixed Fabric solution",
                target_components=(
                    "Dataflow Gen2",
                    "Fabric Notebook",
                    "Fabric Pipeline",
                ),
                recommendation_reason=(
                    assessment.recommendation_reason
                    + "; generated bundle orchestrates Dataflow Gen2 then Fabric Notebook"
                ),
                estimated_effort_days=remaining_effort_days(
                    required_bindings=bindings,
                ),
            )
    labels: tuple[tuple[Target, str], ...] = (
        ("dataflow", "Dataflow Gen2"),
        ("notebook", "Fabric Notebook"),
    )
    for target, label in labels:
        candidate = generate_candidate(path, target)
        if not candidate.deployable:
            continue
        reason = assessment.recommendation_reason
        if assessment.recommended_target != label:
            reason += f"; native compiler routes deployment to {label}"
        return replace(
            assessment,
            recommended_target=label,
            target_components=(label,),
            recommendation_reason=reason,
            estimated_effort_days=remaining_effort_days(
                required_bindings=candidate.required_bindings,
            ),
        )
    return replace(
        assessment,
        recommended_target="Manual rework",
        target_components=(),
        recommendation_reason=(
            assessment.recommendation_reason
            + "; no deployable native Dataflow or Notebook implementation is available"
        ),
        migration_wave="Redesign",
    )


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
                            _apply_native_route(path, assess_workflow(path)),
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
        output = io.BytesIO()
        with zipfile.ZipFile(output, "w") as archive:
            for path in sorted(persisted.root.rglob("*"), key=lambda item: str(item).casefold()):
                if not path.is_file() or not _belongs_to_target(path.name, target):
                    continue
                entry = zipfile.ZipInfo(
                    str(path.relative_to(persisted.root)).replace("\\", "/"),
                    date_time=(1980, 1, 1, 0, 0, 0),
                )
                entry.compress_type = zipfile.ZIP_DEFLATED
                archive.writestr(entry, path.read_bytes())
        return output.getvalue()

    def workflow_package(self, identity: str, workflow: str) -> tuple[bytes, str]:
        """Build a byte-stable archive for one workflow and all generated items."""
        dataflows = self.write_artifacts(identity, "dataflow")
        notebooks = self.write_artifacts(identity, "notebook")
        pipelines = self.write_artifacts(identity, "pipeline")
        candidates = [*dataflows.candidates, *notebooks.candidates, *pipelines.candidates]
        matched = next(
            (candidate for candidate in candidates if candidate.workflow == workflow),
            None,
        )
        if matched is None:
            raise ValueError(f"Workflow was not found in the confirmed run: {workflow}")
        relative = _candidate_artifact_path(matched)
        artifact_root = self.artifact_root.resolve()
        folder = (artifact_root / relative).resolve()
        if not folder.is_relative_to(artifact_root) or not folder.is_dir():
            raise ValueError("Workflow artifact folder is unavailable")
        output = io.BytesIO()
        with zipfile.ZipFile(output, "w") as archive:
            for path in sorted(folder.iterdir(), key=lambda item: item.name.casefold()):
                if not path.is_file() or not _belongs_to_workflow_bundle(path.name):
                    continue
                entry = zipfile.ZipInfo(
                    path.name,
                    date_time=(1980, 1, 1, 0, 0, 0),
                )
                entry.compress_type = zipfile.ZIP_DEFLATED
                archive.writestr(entry, path.read_bytes())
        return output.getvalue(), f"{relative.name}-fabric-bundle.zip"

    def write_artifacts(self, identity: str, target: Target) -> ArtifactWriteResult:
        """Persist both targets together below generated-fabric-workflows/<workflow>."""
        if not re.fullmatch(r"[a-f0-9]{32}", identity):
            raise ValueError("Run ID must be a 32-character lowercase hexadecimal value")
        run = self.get_run(identity)
        candidates = self.generate(identity, target)
        artifact_root = self.artifact_root.resolve()
        artifact_root.mkdir(parents=True, exist_ok=True)
        _write_artifact_guide(artifact_root)
        written: list[Candidate] = []
        index: list[dict[str, object]] = []
        paths: set[Path] = set()
        for position, candidate in enumerate(candidates):
            relative = _candidate_artifact_path(candidate)
            if relative in paths:
                raise ValueError(
                    f"Workflow output path collides after sanitization: {relative}"
                )
            paths.add(relative)
            artifact_path = relative.as_posix()
            folder = (artifact_root / relative).resolve()
            if not folder.is_relative_to(artifact_root):
                raise ValueError("Workflow artifact path escapes the configured output root")
            folder.mkdir(parents=True, exist_ok=True)
            _remove_target_files(folder, target)
            if candidate.validation_state in {"blocked", "scaffold"}:
                files = [f"{target}-diagnostics.json", f"{target}-manifest.json"]
                updated = candidate.model_copy(
                    update={"artifact_path": artifact_path, "definition_files": files}
                )
                _atomic_write_text(
                    folder / f"{target}-diagnostics.json",
                    json.dumps(
                        {
                            "workflow": candidate.workflow,
                            "state": "blocked",
                            "diagnostics": candidate.diagnostics,
                        },
                        indent=2,
                    ),
                )
            else:
                definition = _local_definition_files(
                    target, _fabric_definition(candidate, relative.name)
                )
                files = list(definition)
                updated = candidate.model_copy(
                    update={"artifact_path": artifact_path, "definition_files": files}
                )
                for name, content in definition.items():
                    _atomic_write_text(folder / name, content)
            _atomic_write_text(
                folder / f"{target}-manifest.json", updated.model_dump_json(indent=2)
            )
            written.append(updated)
            index.append(
                {
                    "position": position,
                    "workflow": updated.workflow,
                    "target": updated.target,
                    "state": updated.validation_state,
                    "deployable_definition": updated.deployable,
                    "runtime_ready": updated.runtime_ready,
                    "path": updated.artifact_path,
                    "files": updated.definition_files,
                }
            )
        index_name = f"artifact-index-{target}.json"
        _atomic_write_text(
            artifact_root / index_name,
            json.dumps(
                {
                    "run_id": identity,
                    "target": target,
                    "artifact_count": len(written),
                    "generated_count": sum(item.definition_ready for item in written),
                    "blocked_count": sum(not item.definition_ready for item in written),
                    "artifacts": index,
                },
                indent=2,
            ),
        )
        _write_combined_index(artifact_root, identity)
        _write_deployment_plan(
            artifact_root,
            identity,
            self.generate(identity, "dataflow"),
            self.generate(identity, "notebook"),
            self.generate(identity, "pipeline"),
            run.result.assessments if run.result else [],
        )
        _write_latest_index(artifact_root, identity, target, index_name)
        return ArtifactWriteResult(artifact_root, written)

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
                    workflow_evidence(Path(item.source_path), item.display_path, index)
                ]
            else:
                path = Path(item.source_path)
                detected = self._source_registry.detect(path, item.display_path)
                package = self._source_registry.parse(path, detected.match)
                asset_evidence = [
                    etl_asset_evidence(package, asset, item.display_path, index)
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


def _artifact_path(workflow: str) -> Path:
    parts = [part for part in re.split(r"[\\/!]+", workflow) if part]
    if not parts:
        return Path("workflow")
    parts[-1] = Path(parts[-1]).stem
    clean = [re.sub(r"[^A-Za-z0-9_-]+", "-", part).strip("-")[:80] or "workflow" for part in parts]
    return Path(*clean)


def _candidate_artifact_path(candidate: Candidate) -> Path:
    if candidate.source_platform is SourcePlatform.ALTERYX:
        return _artifact_path(candidate.workflow)
    platform_root = {
        SourcePlatform.INFORMATICA_POWERCENTER: "informatica-powercenter",
        SourcePlatform.INFORMATICA_IDMC: "informatica-idmc",
    }[candidate.source_platform]
    asset_name = candidate.native_id or candidate.workflow.rsplit("!", 1)[-1]
    return Path(platform_root) / _artifact_path(asset_name)


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


def _fabric_definition(candidate: Candidate, slug: str) -> dict[str, str]:
    display_name = Path(candidate.workflow.replace("!", "/")).stem[:120] or slug
    logical_id = str(
        uuid.uuid5(uuid.NAMESPACE_URL, f"{candidate.target}:{candidate.source_sha256}")
    )
    source_label = (
        "Alteryx"
        if candidate.source_platform is SourcePlatform.ALTERYX
        else candidate.source_product
    )
    description = (
        f"Generated from {source_label} static analysis. "
        "Independent semantic validation remains required."
    )
    platform = {
        "$schema": (
            "https://developer.microsoft.com/json-schemas/fabric/"
            "gitIntegration/platformProperties/2.0.0/schema.json"
        ),
        "metadata": {
            "type": {
                "notebook": "Notebook",
                "dataflow": "Dataflow",
                "pipeline": "DataPipeline",
            }[candidate.target],
            "displayName": display_name,
            "description": description,
        },
        "config": {"version": "2.0", "logicalId": logical_id},
    }
    platform_text = json.dumps(platform, indent=2, sort_keys=True)
    if candidate.target == "pipeline":
        request = {
            "displayName": display_name,
            "type": "DataPipeline",
            "description": description,
            "definition": {
                "parts": [
                    _definition_part("pipeline-content.json", candidate.code),
                    _definition_part(".platform", platform_text),
                ]
            },
        }
        return {
            "pipeline-content.json": candidate.code,
            ".platform": platform_text,
            "create-item.json": json.dumps(request, indent=2, sort_keys=True),
        }

    if candidate.target == "notebook":
        notebook = {
            "nbformat": 4,
            "nbformat_minor": 5,
            "metadata": {
                "kernelspec": {
                    "display_name": "Synapse PySpark",
                    "language": "Python",
                    "name": "synapse_pyspark",
                },
                "language_info": {"name": "python"},
            },
            "cells": _notebook_cells(candidate, display_name),
        }
        notebook_text = json.dumps(notebook, indent=2, sort_keys=True)
        request = {
            "displayName": display_name,
            "type": "Notebook",
            "description": description,
            "definition": {
                "format": "ipynb",
                "parts": [
                    _definition_part("notebook-content.ipynb", notebook_text),
                    _definition_part(".platform", platform_text),
                ],
            },
        }
        return {
            "notebook-content.ipynb": notebook_text,
            ".platform": platform_text,
            "create-item.json": json.dumps(request, indent=2, sort_keys=True),
        }

    query_name = re.sub(r"[^A-Za-z0-9_]+", "_", display_name).strip("_") or "MigratedWorkflow"
    if candidate.definition_queries:
        mashup = candidate.code
        query_names = candidate.definition_queries
    else:
        mashup = (
            f"section Section1;\n"
            f"shared #{_m_identifier(query_name)} = {candidate.code.strip()};\n"
        )
        query_names = [query_name]
    metadata = {
        "formatVersion": "202502",
        "computeEngineSettings": {"allowFastCopy": False},
        "name": display_name,
        "queryGroups": [
            {
                "id": group.id,
                "name": group.name,
                "description": group.description,
                "parentId": group.parent_id,
                "order": group.order,
            }
            for group in candidate.query_groups
        ],
        "queriesMetadata": {
            name: {
                "queryId": str(
                    uuid.uuid5(
                        uuid.NAMESPACE_URL,
                        f"query:{candidate.source_sha256}:{name}",
                    )
                ),
                "queryName": name,
                **(
                    {"queryGroupId": candidate.query_group_assignments[name]}
                    if name in candidate.query_group_assignments
                    else {}
                ),
                "loadEnabled": False,
            }
            for name in query_names
        },
        "connections": [],
    }
    metadata_text = json.dumps(metadata, indent=2, sort_keys=True)
    request = {
        "displayName": display_name,
        "type": "Dataflow",
        "description": description,
        "definition": {
            "parts": [
                _definition_part("mashup.pq", mashup),
                _definition_part("queryMetadata.json", metadata_text),
                _definition_part(".platform", platform_text),
            ]
        },
    }
    return {
        "mashup.pq": mashup,
        "queryMetadata.json": metadata_text,
        ".platform": platform_text,
        "create-item.json": json.dumps(request, indent=2, sort_keys=True),
    }


def _notebook_cells(candidate: Candidate, display_name: str) -> list[dict[str, object]]:
    workflow_label = candidate.workflow.replace("`", "\\`")
    statements = _python_statement_blocks(candidate.code)
    imports: list[tuple[ast.stmt, str]] = []
    parameters: list[tuple[ast.stmt, str]] = []
    sources: list[tuple[ast.stmt, str]] = []
    transformations: list[tuple[ast.stmt, str]] = []
    outputs: list[tuple[ast.stmt, str]] = []
    for node, source in statements:
        if isinstance(node, (ast.Import, ast.ImportFrom)) or (
            isinstance(node, ast.FunctionDef)
            and node.name in {"require_transform", "_read_source"}
        ):
            imports.append((node, source))
        elif _is_pipeline_parameter_statement(node, source):
            parameters.append((node, source))
        elif _is_display_statement(node):
            outputs.append((node, source))
        elif not isinstance(node, ast.FunctionDef) and _is_source_statement(source):
            if not source.startswith("source_paths = globals().get("):
                sources.append((node, source))
        else:
            transformations.append((node, source))

    cells = [
        _markdown_cell(
            "\n".join(
                [
                    f"# {display_name}",
                    "",
                    f"Generated from `{workflow_label}` by "
                    f"compiler {candidate.compiler_version}.",
                    "",
                    "## How to use this notebook",
                    "",
                    "1. Review and complete the source configuration.",
                    "2. Run cells from top to bottom.",
                    "3. Inspect the output previews and validate semantic parity.",
                    "",
                    "> **Important:** Generated transformations are unvalidated. "
                    "Confirm schemas, row counts, business rules, and destinations "
                    "before promotion.",
                ]
            )
        )
    ]
    if imports:
        cells.extend(
            [
                _markdown_cell(
                    "## Runtime imports\n\n"
                    "Imports and runtime helpers required by the generated PySpark transformations."
                ),
                _code_cell(_join_statement_blocks(imports), "imports"),
            ]
        )

    if parameters:
        cells.extend(
            [
                _markdown_cell(
                    "## Pipeline parameters\n\n"
                    "Default workflow parameters; overridden when triggered from a "
                    "Fabric Data Pipeline."
                ),
                _code_cell(_join_statement_blocks(parameters), "parameters"),
            ]
        )

    source_keys = _source_binding_keys(candidate.required_bindings)
    if source_keys:
        source_labels = _source_binding_labels(candidate.code)
        table_rows = [
            f"| `{key}` | `{source_labels.get(key, f'Tool {key}')}` |"
            for key in source_keys
        ]
        config_cell = _code_cell(
            "\n".join(
                [
                    "source_paths = {",
                    *[
                        f"    {json.dumps(key)}: \"\",  "
                        f"# {source_labels.get(key, f'Tool {key}')}"
                        for key in source_keys
                    ],
                    "}",
                ]
            ),
            "configuration",
        )
        if not parameters:
            config_cell["metadata"] = {"tags": ["generated", "parameters", "configuration"]}
        cells.extend(
            [
                _markdown_cell(
                    "\n".join(
                        [
                            "## Source configuration",
                            "",
                            "Replace each empty value with an accessible Fabric or "
                            "OneLake path before running the ingestion cells.",
                            "",
                            "| Tool ID | Generated DataFrame |",
                            "| --- | --- |",
                            *table_rows,
                        ]
                    )
                ),
                config_cell,
            ]
        )

    cells.extend(
        _section_cells(
            "Source ingestion",
            "Loads and validates source datasets before transformation.",
            sources,
            chunk_size=12,
            tag="sources",
        )
    )
    source_label = (
        "Alteryx"
        if candidate.source_platform is SourcePlatform.ALTERYX
        else candidate.source_product
    )
    cells.extend(
        _section_cells(
            "Transformations",
            f"Applies the translated {source_label} operations in dependency order.",
            transformations,
            chunk_size=8,
            tag="transformations",
        )
    )
    cells.extend(
        _section_cells(
            "Output preview",
            "Displays terminal DataFrames for review. Replace preview-only output "
            "with approved destination writes after validation.",
            outputs,
            chunk_size=8,
            tag="outputs",
        )
    )
    return cells


def _python_statement_blocks(code: str) -> list[tuple[ast.stmt, str]]:
    lines = code.splitlines()
    tree = ast.parse(code)
    blocks: list[tuple[ast.stmt, str]] = []
    for node in tree.body:
        end = node.end_lineno or node.lineno
        blocks.append((node, "\n".join(lines[node.lineno - 1 : end])))
    return blocks


def _is_display_statement(node: ast.stmt) -> bool:
    return (
        isinstance(node, ast.Expr)
        and isinstance(node.value, ast.Call)
        and isinstance(node.value.func, ast.Name)
        and node.value.func.id == "display"
    )


def _is_pipeline_parameter_statement(node: ast.stmt, source: str) -> bool:
    return (
        isinstance(node, ast.Assign)
        and len(node.targets) == 1
        and isinstance(node.targets[0], ast.Name)
        and "= globals().get(" in source
        and node.targets[0].id not in {"source_paths", "transform_bindings"}
    )


def _is_source_statement(source: str) -> bool:
    return any(
        marker in source
        for marker in (
            "source_paths",
            "_Path",
            "_read_source(",
            "spark.read",
            "spark.createDataFrame",
        )
    )


def _source_binding_keys(bindings: list[str]) -> list[str]:
    keys: list[str] = []
    for binding in bindings:
        match = re.fullmatch(r"""source_paths\[['"]([^'"]+)['"]\]""", binding)
        if match and match.group(1) not in keys:
            keys.append(match.group(1))
    return keys


def _source_binding_labels(code: str) -> dict[str, str]:
    return {
        match.group(2): match.group(1)
        for match in re.finditer(
            r"""(?m)^([A-Za-z_][A-Za-z0-9_]*)_(?:Path|path) = """
            r"""source_paths\.get\(['"]([^'"]+)['"]\)""",
            code,
        )
    }


def _section_cells(
    title: str,
    description: str,
    statements: list[tuple[ast.stmt, str]],
    *,
    chunk_size: int,
    tag: str,
) -> list[dict[str, object]]:
    if not statements:
        return []
    chunks = [
        statements[index : index + chunk_size]
        for index in range(0, len(statements), chunk_size)
    ]
    cells: list[dict[str, object]] = [
        _markdown_cell(f"## {title}\n\n{description}")
    ]
    for index, chunk in enumerate(chunks, start=1):
        names = _assigned_names(chunk)
        label = ", ".join(f"`{name}`" for name in names[:4])
        if len(names) > 4:
            label += f", and {len(names) - 4} more"
        detail = f"\n\nProduces {label}." if label else ""
        cells.extend(
            [
                _markdown_cell(
                    f"### {title} {index} of {len(chunks)}{detail}"
                ),
                _code_cell(_join_statement_blocks(chunk), tag),
            ]
        )
    return cells


def _assigned_names(statements: list[tuple[ast.stmt, str]]) -> list[str]:
    names: list[str] = []
    for node, _ in statements:
        if not isinstance(node, ast.Assign):
            continue
        for target in node.targets:
            if isinstance(target, ast.Name):
                names.append(target.id)
    return names


def _join_statement_blocks(statements: list[tuple[ast.stmt, str]]) -> str:
    return "\n".join(source for _, source in statements)


def _markdown_cell(content: str) -> dict[str, object]:
    return {
        "cell_type": "markdown",
        "metadata": {"tags": ["generated", "documentation"]},
        "source": _notebook_source(content),
    }


def _code_cell(content: str, tag: str) -> dict[str, object]:
    return {
        "cell_type": "code",
        "execution_count": None,
        "metadata": {"tags": ["generated", tag]},
        "outputs": [],
        "source": _notebook_source(content),
    }


def _notebook_source(content: str) -> list[str]:
    return [f"{line}\n" for line in content.splitlines()]


def _definition_part(path: str, content: str) -> dict[str, str]:
    return {
        "path": path,
        "payload": base64.b64encode(content.encode("utf-8")).decode("ascii"),
        "payloadType": "InlineBase64",
    }


def _write_latest_index(
    artifact_root: Path, identity: str, target: Target, index_name: str
) -> None:
    latest = artifact_root / "latest.json"
    content: dict[str, object] = {"run_id": identity, "targets": {}}
    if latest.is_file():
        existing = json.loads(latest.read_text(encoding="utf-8"))
        if isinstance(existing, dict) and existing.get("run_id") == identity:
            content = existing
    targets = content.get("targets")
    if not isinstance(targets, dict):
        targets = {}
        content["targets"] = targets
    targets[target] = index_name
    _atomic_write_text(latest, json.dumps(content, indent=2))


def _write_artifact_guide(artifact_root: Path) -> None:
    _atomic_write_text(
        artifact_root / "DEPLOYMENT.txt",
        "Fabric definition output\n"
        "========================\n\n"
        "Open latest.json to see which assessment run produced the current definitions.\n"
        "Each workflow directory contains target-prefixed Notebook and Dataflow files.\n"
        "The *-create-item.json files are complete Fabric Create Item request bodies.\n"
        "Blocked targets contain *-diagnostics.json and are not deployable definitions.\n\n"
        "Submit definitions only to an approved\n"
        "development workspace with authorized identity and after reviewing source bindings.\n"
        "Generated definitions are unvalidated until source/target semantic parity is accepted.\n"
        "For a new Dataflow, use ApplyChangesIfNeeded on the first refresh after "
        "definition save.\n",
    )


def _local_definition_files(target: Target, definition: dict[str, str]) -> dict[str, str]:
    names = {
        "notebook": {
            "notebook-content.ipynb": "notebook-content.ipynb",
            ".platform": "notebook.platform.json",
            "create-item.json": "notebook-create-item.json",
        },
        "dataflow": {
            "mashup.pq": "dataflow-mashup.pq",
            "queryMetadata.json": "dataflow-queryMetadata.json",
            ".platform": "dataflow.platform.json",
            "create-item.json": "dataflow-create-item.json",
        },
        "pipeline": {
            "pipeline-content.json": "pipeline-content.json",
            ".platform": "pipeline.platform.json",
            "create-item.json": "pipeline-create-item.json",
        },
    }[target]
    return {names[name]: content for name, content in definition.items()}


def _target_file_names(target: Target) -> set[str]:
    names = {f"{target}-manifest.json", f"{target}-diagnostics.json"}
    if target == "notebook":
        return names | {
            "notebook-content.ipynb",
            "notebook.platform.json",
            "notebook-create-item.json",
        }
    if target == "pipeline":
        return names | {
            "pipeline-content.json",
            "pipeline.platform.json",
            "pipeline-create-item.json",
        }
    return names | {
        "dataflow-mashup.pq",
        "dataflow-queryMetadata.json",
        "dataflow.platform.json",
        "dataflow-create-item.json",
    }


def _remove_target_files(folder: Path, target: Target) -> None:
    for name in _target_file_names(target):
        path = folder / name
        if path.is_file():
            path.unlink()


def _write_combined_index(root: Path, run_id: str) -> None:
    targets: dict[str, object] = {}
    for target in ("notebook", "dataflow", "pipeline"):
        path = root / f"artifact-index-{target}.json"
        if path.is_file():
            payload = json.loads(path.read_text(encoding="utf-8"))
            if payload.get("run_id") == run_id:
                targets[target] = payload
    _atomic_write_text(
        root / "artifact-index.json",
        json.dumps({"run_id": run_id, "targets": targets}, indent=2),
    )


def _pipeline_definition(candidate: Candidate, display_name: str) -> dict[str, str]:
    pipeline_name = f"{display_name}_Orchestration"
    description = (
        f"Orchestrates generated Dataflow Gen2 and Fabric Notebook for "
        f"{display_name}."
    )
    content = {
        "properties": {
            "activities": [
                {
                    "type": "RefreshDataflow",
                    "typeProperties": {
                        "dataflowId": "{{DATAFLOW_ITEM_ID}}",
                        "workspaceId": "{{WORKSPACE_ID}}",
                        "notifyOption": "NoNotification",
                    },
                    "policy": {
                        "timeout": "0.12:00:00",
                        "retry": 0,
                        "retryIntervalInSeconds": 30,
                        "secureInput": False,
                        "secureOutput": False,
                    },
                    "name": "Run Dataflow Gen2",
                    "dependsOn": [],
                },
                {
                    "type": "TridentNotebook",
                    "typeProperties": {
                        "notebookId": "{{NOTEBOOK_ITEM_ID}}",
                        "workspaceId": "{{WORKSPACE_ID}}",
                        "parameters": {},
                    },
                    "policy": {
                        "timeout": "0.12:00:00",
                        "retry": 0,
                        "retryIntervalInSeconds": 30,
                        "secureInput": False,
                        "secureOutput": False,
                    },
                    "name": "Run Fabric Notebook",
                    "dependsOn": [
                        {
                            "activity": "Run Dataflow Gen2",
                            "dependencyConditions": ["Succeeded"],
                        }
                    ],
                },
            ]
        }
    }
    platform = {
        "$schema": (
            "https://developer.microsoft.com/json-schemas/fabric/"
            "gitIntegration/platformProperties/2.0.0/schema.json"
        ),
        "metadata": {
            "type": "DataPipeline",
            "displayName": pipeline_name,
            "description": description,
        },
        "config": {
            "version": "2.0",
            "logicalId": str(
                uuid.uuid5(
                    uuid.NAMESPACE_URL,
                    f"pipeline:{candidate.source_sha256}:{pipeline_name}",
                )
            ),
        },
    }
    content_text = json.dumps(content, indent=2, sort_keys=True)
    platform_text = json.dumps(platform, indent=2, sort_keys=True)
    request = {
        "displayName": pipeline_name,
        "type": "DataPipeline",
        "description": description,
        "definition": {
            "parts": [
                _definition_part("pipeline-content.json", content_text),
                _definition_part(".platform", platform_text),
            ]
        },
    }
    bundle = {
        "schemaVersion": "1.0",
        "workflow": candidate.workflow,
        "deploymentOrder": ["Dataflow", "Notebook", "DataPipeline"],
        "items": [
            {
                "key": "dataflow",
                "type": "Dataflow",
                "request": "dataflow-create-item.json",
            },
            {
                "key": "notebook",
                "type": "Notebook",
                "request": "notebook-create-item.json",
            },
            {
                "key": "pipeline",
                "type": "DataPipeline",
                "request": "pipeline-create-item.json",
                "dependsOn": ["dataflow", "notebook"],
            },
        ],
    }
    return {
        "pipeline-content.json": content_text,
        "pipeline.platform.json": platform_text,
        "pipeline-create-item.json": json.dumps(request, indent=2, sort_keys=True),
        "deployment-bundle.json": json.dumps(bundle, indent=2, sort_keys=True),
    }


def _write_deployment_plan(
    root: Path,
    run_id: str,
    dataflows: list[Candidate],
    notebooks: list[Candidate],
    pipelines: list[Candidate],
    assessments: list[WorkflowAssessmentResponse],
) -> None:
    notebook_by_workflow = {candidate.workflow: candidate for candidate in notebooks}
    pipeline_by_workflow = {candidate.workflow: candidate for candidate in pipelines}
    assessment_by_workflow = {assessment.path: assessment for assessment in assessments}
    workflows: list[dict[str, object]] = []
    for dataflow in dataflows:
        notebook = notebook_by_workflow.get(dataflow.workflow)
        pipeline = pipeline_by_workflow.get(dataflow.workflow)
        artifact_path = _candidate_artifact_path(dataflow).as_posix()
        folder = root / Path(*artifact_path.split("/"))
        dataflow_available = dataflow.deployable and (
            folder / "dataflow-create-item.json"
        ).is_file()
        notebook_available = bool(
            notebook
            and notebook.deployable
            and (folder / "notebook-create-item.json").is_file()
        )
        pipeline_available = bool(
            pipeline
            and pipeline.deployable
            and (folder / "pipeline-create-item.json").is_file()
        )
        assessment = assessment_by_workflow.get(dataflow.workflow)
        target_components = set(assessment.target_components) if assessment else set()
        bundle_targets = [
            target
            for component, target in (
                ("Dataflow Gen2", "dataflow"),
                ("Fabric Notebook", "notebook"),
                ("Fabric Pipeline", "pipeline"),
            )
            if component in target_components
        ]
        bundle_required = len(bundle_targets) > 1 and "pipeline" in bundle_targets
        pipeline_files: list[str] = []
        if (
            bundle_required
            and "notebook" in bundle_targets
            and dataflow_available
            and notebook_available
        ):
            pipeline_definition = _pipeline_definition(dataflow, Path(artifact_path).name)
            for name, content in pipeline_definition.items():
                _atomic_write_text(folder / name, content)
            pipeline_files = list(pipeline_definition)
        elif pipeline_available:
            pipeline_files = [
                "pipeline-content.json",
                "pipeline.platform.json",
                "pipeline-create-item.json",
            ]
        else:
            for name in (
                "pipeline-content.json",
                "pipeline.platform.json",
                "pipeline-create-item.json",
                "deployment-bundle.json",
            ):
                path = folder / name
                if path.is_file():
                    path.unlink()
        selected = (
            dataflow
            if dataflow_available
            else notebook
            if notebook_available
            else pipeline
            if pipeline_available
            else None
        )
        component: dict[str, object] | None = None
        selected_components: list[dict[str, object]] = []
        bundle_ready = bool(
            bundle_required
            and pipeline_files
            and ("dataflow" not in bundle_targets or dataflow_available)
            and ("notebook" not in bundle_targets or notebook_available)
        )
        if bundle_ready:
            component_definitions: dict[str, dict[str, object]] = {
                "dataflow": {
                    "type": "Dataflow",
                    "target": "dataflow",
                    "path": artifact_path,
                    "definition_files": [
                        "dataflow-mashup.pq",
                        "dataflow-queryMetadata.json",
                        "dataflow.platform.json",
                        "dataflow-create-item.json",
                    ],
                },
                "notebook": {
                    "type": "Notebook",
                    "target": "notebook",
                    "path": artifact_path,
                    "definition_files": [
                        "notebook-content.ipynb",
                        "notebook.platform.json",
                        "notebook-create-item.json",
                    ],
                },
                "pipeline": {
                    "type": "DataPipeline",
                    "target": "pipeline",
                    "path": artifact_path,
                    "definition_files": pipeline_files,
                },
            }
            selected_components = [
                component_definitions[target] for target in bundle_targets
            ]
            bundle = {
                "schemaVersion": "1.0",
                "workflow": dataflow.workflow,
                "deploymentOrder": [
                    component_definitions[target]["type"] for target in bundle_targets
                ],
                "items": [
                    {
                        "key": target,
                        "type": component_definitions[target]["type"],
                        "request": f"{target}-create-item.json",
                        **(
                            {
                                "dependsOn": [
                                    dependency
                                    for dependency in bundle_targets
                                    if dependency != "pipeline"
                                ]
                            }
                            if target == "pipeline"
                            else {}
                        ),
                    }
                    for target in bundle_targets
                ],
            }
            _atomic_write_text(
                folder / "deployment-bundle.json",
                json.dumps(bundle, indent=2, sort_keys=True),
            )
            if "deployment-bundle.json" not in pipeline_files:
                pipeline_files.append("deployment-bundle.json")
        elif selected is not None:
            component = {
                "type": {
                    "dataflow": "Dataflow",
                    "notebook": "Notebook",
                    "pipeline": "DataPipeline",
                }[selected.target],
                "target": selected.target,
                "path": artifact_path,
                "definition_files": (
                    [
                        "dataflow-mashup.pq",
                        "dataflow-queryMetadata.json",
                        "dataflow.platform.json",
                        "dataflow-create-item.json",
                    ]
                    if selected.target == "dataflow"
                    else [
                        "notebook-content.ipynb",
                        "notebook.platform.json",
                        "notebook-create-item.json",
                    ]
                    if selected.target == "notebook"
                    else pipeline_files
                ),
            }
            selected_components = [component]
        diagnostics = [
            *[f"dataflow: {message}" for message in dataflow.diagnostics],
            *(
                [f"notebook: {message}" for message in notebook.diagnostics]
                if notebook
                else ["notebook: candidate missing"]
            ),
            *(
                [f"pipeline: {message}" for message in pipeline.diagnostics]
                if pipeline
                else ["pipeline: candidate missing"]
            ),
        ]
        workflow_entry: dict[str, object] = {
            "workflow": dataflow.workflow,
            "artifact_path": artifact_path,
            "status": "native_ready" if selected_components else "compiler_required",
            "routing_order": ["dataflow", "notebook", "pipeline"],
            "selected_components": selected_components,
            "pipeline_required": bundle_required,
            "diagnostics": diagnostics if not selected_components else [],
        }
        workflows.append(workflow_entry)
        _atomic_write_text(
            folder / "README.md",
            _workflow_bundle_readme(workflow_entry, folder),
        )
    _atomic_write_text(
        root / "deployment-plan.json",
        json.dumps(
            {
                "run_id": run_id,
                "routing_policy": "Dataflow Gen2, then Fabric Notebook, then Pipeline/mix",
                "workflow_count": len(workflows),
                "native_ready_count": sum(
                    workflow["status"] == "native_ready" for workflow in workflows
                ),
                "compiler_required_count": sum(
                    workflow["status"] == "compiler_required" for workflow in workflows
                ),
                "workflows": workflows,
            },
            indent=2,
        ),
    )


def _workflow_bundle_readme(workflow: dict[str, object], folder: Path) -> str:
    source = str(workflow["workflow"])
    display_name = _artifact_path(source).name
    status = str(workflow["status"])
    files = sorted(
        (
            path.name
            for path in folder.iterdir()
            if path.is_file()
            and path.name != "README.md"
            and _belongs_to_workflow_bundle(path.name)
        ),
        key=str.casefold,
    )
    file_rows = [
        f"| `{name}` | {_bundle_file_description(name)} |"
        for name in files
    ]
    request_files = [
        name
        for name in (
            "dataflow-create-item.json",
            "notebook-create-item.json",
            "pipeline-create-item.json",
        )
        if name in files
    ]
    deployment_commands = []
    for request_file in request_files:
        deployment_commands.extend(
            [
                f"# Create the item described by {request_file}",
                "az rest --method post `",
                '  --resource "https://api.fabric.microsoft.com" `',
                '  --url "https://api.fabric.microsoft.com/v1/workspaces/'
                '$WorkspaceId/items" `',
                '  --headers "Content-Type=application/json" `',
                f'  --body "@{request_file}"',
                "",
            ]
        )
    if not deployment_commands:
        deployment_commands = [
            "# No deployable create-item envelope is available.",
            "# Review the diagnostics files and complete the missing implementation.",
        ]
    pipeline_note = ""
    if "pipeline-create-item.json" in files:
        dependencies = [
            label
            for filename, label in (
                ("dataflow-create-item.json", "Dataflow"),
                ("notebook-create-item.json", "Notebook"),
            )
            if filename in files
        ]
        dependency_summary = " and ".join(dependencies) or "compute items"
        placeholders = ["`{{WORKSPACE_ID}}`"]
        if "dataflow-create-item.json" in files:
            placeholders.append("`{{DATAFLOW_ITEM_ID}}`")
        if "notebook-create-item.json" in files:
            placeholders.append("`{{NOTEBOOK_ITEM_ID}}`")
        pipeline_note = f"""
### Pipeline dependency IDs

Deploy the {dependency_summary} first. Capture the returned item IDs, replace
{", ".join(placeholders)} in
`pipeline-content.json`, then rebuild the `pipeline-content.json` Base64 payload
inside `pipeline-create-item.json` before creating the pipeline.
"""
    diagnostics = workflow.get("diagnostics")
    diagnostic_lines = (
        [f"- {value}" for value in diagnostics]
        if isinstance(diagnostics, list) and diagnostics
        else ["- No compiler diagnostics were recorded."]
    )
    return "\n".join(
        [
            f"# {display_name} Fabric workflow bundle",
            "",
            f"Source workflow: `{source}`",
            "",
            f"Generation status: `{status}`",
            "",
            "> [!IMPORTANT]",
            "> Independent semantic validation remains required. Generated definitions",
            "> can be structurally deployable while source connections, destinations,",
            "> credentials, schemas, and business parity still require configuration.",
            "",
            "## Bundle contents",
            "",
            "| File | Purpose |",
            "| --- | --- |",
            *file_rows,
            "",
            "## Manual deployment",
            "",
            "### Prerequisites",
            "",
            "- PowerShell 7 and Azure CLI.",
            "- A Microsoft Fabric workspace on active capacity.",
            "- Contributor or higher permission on the target workspace.",
            "- Permission to create the included Fabric item types.",
            "- Approved source connections and destination items.",
            "",
            "### Authenticate and select the workspace",
            "",
            "```powershell",
            "az login",
            '$WorkspaceId = "<fabric-workspace-guid>"',
            "```",
            "",
            "### Configure bindings before deployment",
            "",
            "Review the decoded definition files before using the request envelopes.",
            "Dataflow source and destination bindings are intentionally unresolved when",
            "workspace connection IDs cannot be inferred. Notebook `source_paths` values",
            "must be completed before execution. If a decoded definition changes, update",
            "the matching Base64 part in its `*-create-item.json` envelope.",
            "",
            "### Create the generated items",
            "",
            "Run the following commands from this extracted bundle directory. Create",
            "items in Dataflow, Notebook, then Data Pipeline order when all are present.",
            "",
            "```powershell",
            *deployment_commands,
            "```",
            pipeline_note.strip(),
            "",
            "## Post-deployment verification",
            "",
            "1. Open each created item in the Fabric workspace.",
            "2. Configure and test source connections and destination bindings.",
            "3. Run source previews before the first full execution.",
            "4. Compare schemas, row counts, null behavior, and business calculations",
            "   with the Alteryx workflow.",
            "5. Promote only after independent parity and operational validation.",
            "",
            "## Compiler diagnostics",
            "",
            *diagnostic_lines,
            "",
        ]
    )


def _bundle_file_description(name: str) -> str:
    descriptions = {
        "dataflow-mashup.pq": "Power Query M transformations.",
        "dataflow-queryMetadata.json": "Dataflow queries, groups, loads, and connections.",
        "dataflow.platform.json": "Dataflow Fabric item metadata.",
        "dataflow-create-item.json": "Fabric REST create-item request for the Dataflow.",
        "notebook-content.ipynb": "Documented Fabric PySpark notebook.",
        "notebook.platform.json": "Notebook Fabric item metadata.",
        "notebook-create-item.json": "Fabric REST create-item request for the Notebook.",
        "pipeline-content.json": "Fabric Data Pipeline activity definition.",
        "pipeline.platform.json": "Pipeline Fabric item metadata.",
        "pipeline-create-item.json": "Fabric REST create-item request for the pipeline.",
        "deployment-bundle.json": "Deployment order and item dependencies.",
    }
    if name in descriptions:
        return descriptions[name]
    if name.endswith("-manifest.json"):
        return "Generated candidate status, bindings, and diagnostics."
    if name.endswith("-diagnostics.json"):
        return "Compiler blockers that require implementation."
    return "Generated workflow artifact."


def _atomic_write_text(path: Path, content: str) -> None:
    temporary = path.with_name(f".{path.name}.{uuid.uuid4().hex}.tmp")
    temporary.write_text(content, encoding="utf-8")
    temporary.replace(path)


def _belongs_to_target(name: str, target: Target) -> bool:
    return (
        name in _target_file_names(target)
        or name in {f"artifact-index-{target}.json", "DEPLOYMENT.txt", "latest.json"}
    )


def _belongs_to_workflow_bundle(name: str) -> bool:
    return (
        name == "README.md"
        or name == "deployment-bundle.json"
        or name.startswith(("dataflow-", "notebook-", "pipeline-"))
        or name
        in {
            "dataflow.platform.json",
            "notebook.platform.json",
            "pipeline.platform.json",
        }
    )


def _m_identifier(value: str) -> str:
    return '"' + value.replace("#", "#(#)").replace('"', '""') + '"'
