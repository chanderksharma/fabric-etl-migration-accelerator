"""Target-neutral portfolio assessment schemas."""

from __future__ import annotations

from pydantic import BaseModel, ConfigDict

from etl_migration_core.contracts.ir import AssetType, SourcePlatform, SourcePlatformId
from etl_migration_core.contracts.spi import NeutralWorkloadProfile
from etl_migration_core.intake.domain import InputKind, SkipReason


class WorkflowCandidateResponse(BaseModel):
    """Serializable workflow candidate."""

    model_config = ConfigDict(from_attributes=True)

    source_path: str
    display_path: str
    extension: str
    size_bytes: int
    sha256: str
    archive_path: str | None
    archive_chain: list[str] = []
    source_platform: SourcePlatformId = SourcePlatform.ALTERYX
    source_product: str = "Alteryx Designer"
    asset_type: str = "workflow"
    adapter_id: str = "alteryx"
    adapter_version: str = "1.0.0"
    parser_version: str | None = None
    registry_version: str | None = None
    rules_version: str | None = None


class SkippedItemResponse(BaseModel):
    """Serializable skipped item."""

    model_config = ConfigDict(from_attributes=True)

    path: str
    reason: SkipReason
    detail: str


class DiscoverySummaryResponse(BaseModel):
    """Serializable pre-run discovery summary."""

    input_path: str
    input_kind: InputKind
    workflow_count: int
    skipped_count: int
    total_size_bytes: int
    workflows: list[WorkflowCandidateResponse]
    skipped: list[SkippedItemResponse]


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
