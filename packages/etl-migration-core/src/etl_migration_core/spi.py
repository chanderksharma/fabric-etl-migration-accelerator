"""Shared Service Provider Interface (SPI) contracts and neutral models."""

from __future__ import annotations

from collections.abc import Sequence
from pathlib import Path
from typing import Literal, Protocol, runtime_checkable

from pydantic import BaseModel, ConfigDict, Field

from etl_migration_core.ir import EtlAsset, EtlPackage, SourcePlatform

IR_SPI_VERSION = "1.0.0"

TargetCapability = Literal[
    "evaluate",
    "capacity",
    "codegen",
    "validate",
    "dry_run",
    "deploy",
]


class UnsupportedTargetCapabilityError(NotImplementedError):
    """Raised when a target provider or capability is a roadmap placeholder."""

    def __init__(self, platform_id: str, detail: str) -> None:
        super().__init__(detail)
        self.platform_id = platform_id
        self.detail = detail


class TargetPlatformInfo(BaseModel):
    """Public capability metadata for a registered target platform."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    platform_id: str = Field(min_length=1, max_length=64)
    display_name: str = Field(min_length=1, max_length=128)
    provider_version: str = Field(min_length=1, max_length=64)
    supported_ir_versions: tuple[str, ...] = ("1.0.0",)
    implemented: bool = False
    status: Literal["ready", "placeholder"] = "placeholder"
    capabilities: tuple[TargetCapability, ...] = ()
    description: str = ""


class TargetEvaluation(BaseModel):
    """Target-platform fit evaluation decoupled from source assessment records."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    platform_id: str = Field(min_length=1, max_length=64)
    implemented: bool = True
    recommended_target: str
    target_components: tuple[str, ...] = ()
    recommendation_reason: str
    required_bindings: tuple[str, ...] = ()
    estimated_effort_days: float | None = None
    migration_wave_override: str | None = None
    diagnostics: tuple[str, ...] = ()


class NeutralWorkloadProfile(BaseModel):
    """Target-agnostic static workload counts extracted from source ETL graphs."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    source_platform: SourcePlatform
    profile_kind: Literal["alteryx", "informatica"]
    counts: dict[str, int]
    total_steps: int = 0
    heavy_steps: int = 0
    script_steps: int = 0
    orchestration_steps: int = 0
    covered_by_linked_mapping: bool = False


@runtime_checkable
class TargetEvaluator(Protocol):
    """Evaluate canonical or staged workflows against a target platform."""

    def evaluate_alteryx_path(
        self,
        path: Path,
        *,
        unsupported_tools: Sequence[str],
        default_target: str,
        default_components: Sequence[str],
        default_reason: str,
    ) -> TargetEvaluation: ...

    def evaluate_asset(
        self,
        package: EtlPackage,
        asset: EtlAsset,
        *,
        base_reason: str,
    ) -> TargetEvaluation: ...


@runtime_checkable
class TargetPlatformProvider(Protocol):
    """Pluggable provider bundle for one migration destination platform."""

    @property
    def platform_id(self) -> str: ...

    @property
    def display_name(self) -> str: ...

    @property
    def provider_version(self) -> str: ...

    @property
    def supported_ir_versions(self) -> tuple[str, ...]: ...

    @property
    def implemented(self) -> bool: ...

    @property
    def capabilities(self) -> tuple[TargetCapability, ...]: ...

    @property
    def description(self) -> str: ...

    def info(self) -> TargetPlatformInfo: ...

    def evaluator(self) -> TargetEvaluator | None: ...


@runtime_checkable
class DeliveryChannel(Protocol):
    """Transport-only CI/CD delivery channel decoupled from target generation."""

    @property
    def channel_id(self) -> str: ...

    @property
    def display_name(self) -> str: ...

    def is_configured(self) -> bool: ...
