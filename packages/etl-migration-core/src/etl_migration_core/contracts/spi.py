"""Shared Service Provider Interface (SPI) contracts and neutral models."""

from __future__ import annotations

from collections.abc import Sequence
from pathlib import Path
from typing import Literal, Protocol, runtime_checkable

from pydantic import BaseModel, ConfigDict, Field, JsonValue

from etl_migration_core.contracts.ir import (
    EtlAsset,
    EtlPackage,
    SourceLocation,
    SourcePlatformId,
)

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
    target_kinds: tuple[str, ...] = ()
    description: str = ""


class Diagnostic(BaseModel):
    """Structured diagnostic emitted during intake, evaluation, or compilation."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    code: str = Field(min_length=1, max_length=64)
    severity: Literal["info", "warning", "error"] = "warning"
    stage: Literal[
        "plugin",
        "intake",
        "parse",
        "assess",
        "evaluate",
        "compile",
        "validate",
        "package",
        "deploy",
    ] = "compile"
    message: str = Field(min_length=1, max_length=2000)
    source_location: SourceLocation | None = None
    remediation: str | None = Field(default=None, max_length=1000)


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
    structured_diagnostics: tuple[Diagnostic, ...] = ()


class TargetArtifact(BaseModel):
    """Target-agnostic generated definition or fail-closed scaffold descriptor."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    workflow: str = Field(min_length=1, max_length=512)
    target_kind: str = Field(min_length=1, max_length=64)
    validation_state: Literal["blocked", "generated_unvalidated", "scaffold"]
    translation_mode: Literal["native", "scaffold"] = "native"
    deployable: bool = False
    artifact_path: str | None = None
    files: dict[str, str] = Field(default_factory=dict)
    diagnostics: tuple[str, ...] = ()
    structured_diagnostics: tuple[Diagnostic, ...] = ()
    required_bindings: tuple[str, ...] = ()
    metadata: dict[str, JsonValue] = Field(default_factory=dict)


class TargetGenerationResult(BaseModel):
    """Target-neutral container returned by a TargetCodeGenerator plugin."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    platform_id: str = Field(min_length=1, max_length=64)
    provider_version: str = Field(min_length=1, max_length=64)
    target_kind: str = Field(min_length=1, max_length=64)
    artifacts: tuple[TargetArtifact, ...] = ()


class TargetCapacityRecommendation(BaseModel):
    """Target-neutral sizing tier recommendation (SKU, DBU, warehouse credits, etc.)."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    scenario: str = Field(min_length=1, max_length=64)
    required_units: float = Field(ge=0)
    unit_label: str = Field(min_length=1, max_length=64)
    recommended_tier: str = Field(min_length=1, max_length=128)


class TargetCapacityResult(BaseModel):
    """Target-neutral capacity estimate returned by a TargetCapacityEstimator plugin."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    platform_id: str = Field(min_length=1, max_length=64)
    provider_version: str = Field(min_length=1, max_length=64)
    model_version: str = Field(min_length=1, max_length=64)
    status: str = Field(min_length=1, max_length=64)
    asset_count: int = Field(ge=0)
    modeled_count: int = Field(ge=0)
    excluded_count: int = Field(ge=0)
    summary_metrics: dict[str, float | int | str] = Field(default_factory=dict)
    recommendations: tuple[TargetCapacityRecommendation, ...] = ()


class NeutralWorkloadProfile(BaseModel):
    """Target-agnostic static workload counts extracted from source ETL graphs."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    source_platform: SourcePlatformId
    profile_kind: Literal["alteryx", "informatica", "generic"]
    counts: dict[str, int]
    total_steps: int = 0
    heavy_steps: int = 0
    script_steps: int = 0
    orchestration_steps: int = 0
    covered_by_linked_mapping: bool = False


@runtime_checkable
class TargetEvaluator(Protocol):
    """Evaluate a canonical asset against a target platform."""

    def evaluate_asset(
        self,
        package: EtlPackage,
        asset: EtlAsset,
        *,
        base_reason: str,
    ) -> TargetEvaluation: ...


@runtime_checkable
class AlteryxPathTargetEvaluator(Protocol):
    """Optional legacy evaluation for providers that accept staged Alteryx paths."""

    def evaluate_alteryx_path(
        self,
        path: Path,
        *,
        unsupported_tools: Sequence[str],
        default_target: str,
        default_components: Sequence[str],
        default_reason: str,
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
class TargetCodeGenerator(Protocol):
    """Optional capability protocol for target-specific code/artifact generation."""

    @property
    def supported_target_kinds(self) -> tuple[str, ...]: ...

    def generate_package(
        self,
        package: EtlPackage,
        *,
        target_kind: str,
        display_path: str | None = None,
    ) -> TargetGenerationResult: ...


@runtime_checkable
class TargetCodeGeneratorProvider(Protocol):
    """Optional provider extension exposing a TargetCodeGenerator."""

    def code_generator(self) -> TargetCodeGenerator | None: ...


@runtime_checkable
class TargetCapacityEstimator(Protocol):
    """Optional capability protocol for target-specific capacity/cost sizing."""

    def estimate_package_capacity(
        self,
        package: EtlPackage,
    ) -> TargetCapacityResult: ...


@runtime_checkable
class TargetCapacityProvider(Protocol):
    """Optional provider extension exposing a TargetCapacityEstimator."""

    def capacity_estimator(self) -> TargetCapacityEstimator | None: ...
