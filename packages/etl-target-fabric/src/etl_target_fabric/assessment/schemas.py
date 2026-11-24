"""API response schemas."""

from pydantic import BaseModel, ConfigDict

from etl_migration_core.contracts.ir import AssetType, SourcePlatform
from etl_migration_core.intake.schemas import (
    DiscoverySummaryResponse as DiscoverySummaryResponse,
)
from etl_migration_core.intake.schemas import (
    SkippedItemResponse as SkippedItemResponse,
)
from etl_migration_core.intake.schemas import (
    WorkflowCandidateResponse as WorkflowCandidateResponse,
)
from etl_target_fabric.capacity.model import CapacityStaticProfile


class ToolInventoryResponse(BaseModel):
    """Serializable tool inventory entry."""

    model_config = ConfigDict(from_attributes=True)

    name: str
    count: int
    support: str


class WorkflowAssessmentResponse(BaseModel):
    """Serializable deterministic workflow assessment."""

    model_config = ConfigDict(from_attributes=True)

    path: str
    tool_count: int
    connection_count: int
    tools: list[ToolInventoryResponse]
    complexity_score: int
    complexity_band: str
    recommended_target: str
    target_components: list[str]
    recommendation_reason: str
    unsupported_tools: list[str]
    migration_wave: str
    estimated_effort_days: float
    registry_version: str
    rules_version: str
    dependencies: list[str] = []
    data_sources: list[str] = []
    graph_schema_version: str = "1.0.0"
    source_platform: SourcePlatform = SourcePlatform.ALTERYX
    source_product: str = "Alteryx Designer"
    asset_type: AssetType = AssetType.WORKFLOW
    native_id: str | None = None
    folder: str | None = None
    capacity_profile: CapacityStaticProfile | None = None


class EstateAssessmentResponse(BaseModel):
    """Assessment result for every successfully parsed workflow."""

    workflow_count: int
    failed_count: int
    assessments: list[WorkflowAssessmentResponse]
    failures: list[str]
    workflows: list[WorkflowCandidateResponse] = []
    skipped: list[SkippedItemResponse] = []
