"""Shared serializable discovery schemas reused across assessment and target packages."""

from __future__ import annotations

from pydantic import BaseModel, ConfigDict

from etl_migration_core.contracts.ir import SourcePlatform, SourcePlatformId
from etl_migration_core.intake.domain import DiscoverySummary, InputKind, SkipReason


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

    @classmethod
    def from_summary(cls, summary: DiscoverySummary) -> DiscoverySummaryResponse:
        """Convert a domain ``DiscoverySummary`` into a serializable response model."""
        return cls(
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
