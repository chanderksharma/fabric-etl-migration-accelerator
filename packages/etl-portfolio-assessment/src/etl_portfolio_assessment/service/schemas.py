"""Target-neutral portfolio assessment schemas."""

from __future__ import annotations

from pydantic import BaseModel, ConfigDict

from etl_migration_core.contracts.ir import AssetType, SourcePlatformId
from etl_migration_core.contracts.spi import NeutralWorkloadProfile
from etl_migration_core.intake.schemas import (
    DiscoverySummaryResponse as DiscoverySummaryResponse,
)
from etl_migration_core.intake.schemas import (
    SkippedItemResponse as SkippedItemResponse,
)
from etl_migration_core.intake.schemas import (
    WorkflowCandidateResponse as WorkflowCandidateResponse,
)


class NeutralComponentResponse(BaseModel):
    """Target-neutral operation inventory entry."""

    model_config = ConfigDict(from_attributes=True)

    operation: str
    count: int
    classification: str


class NeutralAssessmentResponse(BaseModel):
    """Target-agnostic portfolio assessment response."""

    model_config = ConfigDict(from_attributes=True)

    path: str
    native_id: str
    name: str
    folder: str | None = None
    source_platform: SourcePlatformId
    source_product: str
    asset_type: AssetType
    component_count: int
    connection_count: int
    inventory: list[NeutralComponentResponse]
    complexity_score: int
    complexity_band: str
    intrinsic_effort_days: float
    wave_tier: str
    unknown_components: list[str]
    dependencies: list[str] = []
    data_sources: list[str] = []
    rules_version: str
    workload_profile: NeutralWorkloadProfile | None = None


class NeutralEstateAssessmentResponse(BaseModel):
    """Target-agnostic portfolio assessment summary across discovered exports."""

    workflow_count: int
    failed_count: int
    assessments: list[NeutralAssessmentResponse]
    failures: list[str]
    workflows: list[WorkflowCandidateResponse] = []
    skipped: list[SkippedItemResponse] = []
