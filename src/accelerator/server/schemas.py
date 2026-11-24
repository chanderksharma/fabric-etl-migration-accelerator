"""Request and response models for the local API."""

from __future__ import annotations

from pydantic import BaseModel, Field

from accelerator.runtime.models import RunStatus
from etl_migration_core.contracts.spi import Diagnostic
from etl_migration_core.host import SourceDescriptor, TargetDescriptor
from etl_migration_core.plugins import PluginLoadResult
from etl_migration_core.targets.registry import TargetProviderFault
from etl_target_fabric.compilers.alteryx import Target


class LocalSelection(BaseModel):
    path: str = Field(min_length=1)


class FolderSelectionResponse(BaseModel):
    path: str | None = None


class Confirmation(BaseModel):
    snapshot_id: str = Field(pattern=r"^[a-f0-9]{64}$")


class DevSelection(BaseModel):
    workspace: str = Field(min_length=1)
    target: Target = "notebook"


class PublicationReference(BaseModel):
    run_id: str
    digest: str


class SourcesResponse(BaseModel):
    sources: list[SourceDescriptor]


class PluginsResponse(BaseModel):
    allowlist: list[str] | None
    failed_count: int
    plugins: list[PluginLoadResult]
    diagnostics: list[Diagnostic]


class TargetsResponse(BaseModel):
    targets: list[TargetDescriptor]
    faults: list[TargetProviderFault]


class RunListResponse(BaseModel):
    total: int
    limit: int
    offset: int
    runs: list[RunStatus]
