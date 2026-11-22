"""Pydantic models returned by the run service and exposed by the local API."""

from __future__ import annotations

from pathlib import Path
from typing import Literal

from pydantic import BaseModel, TypeAdapter

from etl_migration_core.contracts.spi import TargetEvaluation
from etl_target_fabric.assessment.schemas import DiscoverySummaryResponse, EstateAssessmentResponse
from etl_target_fabric.compilers.alteryx import Candidate, Target

RunState = Literal["queued", "running", "completed", "failed", "cancelled"]


class SnapshotPreview(DiscoverySummaryResponse):
    snapshot_id: str


class Run(BaseModel):
    id: str
    snapshot_id: str
    status: RunState
    processed: int
    total: int
    cache_hits: int
    error: str | None = None
    timings: dict[str, float] | None = None
    result: EstateAssessmentResponse | None = None


class RunStatus(BaseModel):
    """Lightweight status view without serialized portfolio payload."""

    id: str
    snapshot_id: str
    status: RunState
    processed: int
    total: int
    cache_hits: int
    error: str | None = None
    timings: dict[str, float] | None = None


class RunTargetEvaluation(BaseModel):
    """Target evaluation linked to a source asset in a confirmed run."""

    source_path: str
    asset_id: str
    asset_name: str
    ir_version: str
    provider_version: str
    evaluation: TargetEvaluation


class GenerationJob(BaseModel):
    """Durable generation request. Completed jobs carry candidates; they do not write files."""

    id: str
    run_id: str
    target: Target
    status: RunState
    attempts: int = 0
    error: str | None = None
    candidates: list[Candidate] | None = None


class ArtifactPublication(BaseModel):
    """Content-addressed, run-scoped local artifact publication."""

    run_id: str
    digest: str
    root: Path


TARGET_EVALUATION_LIST = TypeAdapter(list[RunTargetEvaluation])
