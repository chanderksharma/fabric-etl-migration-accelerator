"""Compiler-grounded Fabric routing, applied after a static portfolio assessment."""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import replace
from pathlib import Path
from typing import TYPE_CHECKING, NamedTuple

from etl_migration_core.contracts.ir import EtlAsset, EtlPackage
from etl_migration_core.contracts.spi import TargetEvaluation
from etl_migration_core.planning.effort import remaining_effort_days
from etl_target_fabric.assessment.schemas import WorkflowAssessmentResponse
from etl_target_fabric.assessment.support_matrix import migration_wave
from etl_target_fabric.compilers.alteryx import Target, generate_candidate
from etl_target_fabric.compilers.ir import compile_asset_targets

if TYPE_CHECKING:
    from etl_migration_core.sources.alteryx.graph import WorkflowGraph
    from etl_target_fabric.assessment.ir_assessment import EtlAssessment
    from etl_target_fabric.assessment.workflow import WorkflowAssessment
    from etl_target_fabric.compilers.ir import EtlCompiledTargets


def evaluate_alteryx_native_route(
    path: Path,
    *,
    unsupported_tools: Sequence[str],
    default_target: str,
    default_components: Sequence[str],
    default_reason: str,
    graph: WorkflowGraph | None = None,
) -> TargetEvaluation:
    """Evaluate Fabric target fit for an Alteryx workflow without mutating assessment."""
    if (
        unsupported_tools
        and {"Dataflow Gen2", "Fabric Notebook"}.issubset(default_components)
    ):
        dataflow = generate_candidate(path, "dataflow", graph=graph)
        notebook = generate_candidate(path, "notebook", graph=graph)
        if dataflow.deployable and notebook.deployable:
            bindings = (*dataflow.required_bindings, *notebook.required_bindings)
            return TargetEvaluation(
                platform_id="fabric",
                implemented=True,
                recommended_target="Mixed Fabric solution",
                target_components=(
                    "Dataflow Gen2",
                    "Fabric Notebook",
                    "Fabric Pipeline",
                ),
                recommendation_reason=(
                    default_reason
                    + "; generated bundle orchestrates Dataflow Gen2 then Fabric Notebook"
                ),
                required_bindings=bindings,
                estimated_effort_days=remaining_effort_days(
                    required_bindings=bindings,
                ),
            )
    labels: tuple[tuple[Target, str], ...] = (
        ("dataflow", "Dataflow Gen2"),
        ("notebook", "Fabric Notebook"),
    )
    for target, label in labels:
        candidate = generate_candidate(path, target, graph=graph)
        if not candidate.deployable:
            continue
        reason = default_reason
        if default_target != label:
            reason += f"; native compiler routes deployment to {label}"
        return TargetEvaluation(
            platform_id="fabric",
            implemented=True,
            recommended_target=label,
            target_components=(label,),
            recommendation_reason=reason,
            required_bindings=tuple(candidate.required_bindings),
            estimated_effort_days=remaining_effort_days(
                required_bindings=candidate.required_bindings,
            ),
        )
    return TargetEvaluation(
        platform_id="fabric",
        implemented=True,
        recommended_target="Manual rework",
        target_components=(),
        recommendation_reason=(
            default_reason
            + "; no deployable native Dataflow or Notebook implementation is available"
        ),
        migration_wave_override="Redesign",
    )


def evaluate_etl_native_route(
    package: EtlPackage,
    asset: EtlAsset,
    *,
    base_reason: str,
    compiled: EtlCompiledTargets | None = None,
) -> TargetEvaluation:
    """Evaluate Fabric target fit using one shared set of compiled definitions."""
    candidates = compiled or compile_asset_targets(package, asset)
    if candidates.dataflow.deployable and candidates.pipeline.deployable:
        bindings = (
            *candidates.dataflow.required_bindings,
            *candidates.pipeline.required_bindings,
        )
        return TargetEvaluation(
            platform_id="fabric",
            implemented=True,
            recommended_target="Mixed Fabric solution",
            target_components=("Dataflow Gen2", "Fabric Pipeline"),
            recommendation_reason=(
                base_reason
                + "; native compiler emits a Dataflow and dependent Fabric Pipeline"
            ),
            required_bindings=bindings,
            estimated_effort_days=remaining_effort_days(
                required_bindings=bindings,
            ),
        )
    if candidates.notebook.deployable and candidates.pipeline.deployable:
        bindings = (
            *candidates.notebook.required_bindings,
            *candidates.pipeline.required_bindings,
        )
        return TargetEvaluation(
            platform_id="fabric",
            implemented=True,
            recommended_target="Mixed Fabric solution",
            target_components=("Fabric Notebook", "Fabric Pipeline"),
            recommendation_reason=(
                base_reason
                + "; native compiler emits a Fabric Notebook and dependent Fabric Pipeline"
            ),
            required_bindings=bindings,
            estimated_effort_days=remaining_effort_days(
                required_bindings=bindings,
            ),
        )
    for candidate, label in (
        (candidates.dataflow, "Dataflow Gen2"),
        (candidates.notebook, "Fabric Notebook"),
        (candidates.pipeline, "Fabric Pipeline"),
    ):
        if candidate.deployable:
            return TargetEvaluation(
                platform_id="fabric",
                implemented=True,
                recommended_target=label,
                target_components=(label,),
                recommendation_reason=(
                    base_reason
                    + f"; native compiler routes deployment to {label}"
                ),
                required_bindings=tuple(candidate.required_bindings),
                estimated_effort_days=remaining_effort_days(
                    required_bindings=candidate.required_bindings,
                ),
            )
    diagnostics = sorted(
        {
            message
            for candidate in candidates.values()
            for message in candidate.diagnostics
        }
    )
    detail = "; ".join(diagnostics[:3]) or "compiler coverage is unavailable"
    return TargetEvaluation(
        platform_id="fabric",
        implemented=True,
        recommended_target="Manual rework",
        target_components=(),
        recommendation_reason=(
            base_reason
            + f"; no deployable native implementation is available: {detail}"
        ),
        migration_wave_override="Redesign",
        diagnostics=tuple(diagnostics),
    )


class _Routing(NamedTuple):
    """The assessment fields a confirmed Fabric evaluation replaces."""

    recommended_target: str
    target_components: tuple[str, ...]
    recommendation_reason: str
    estimated_effort_days: float
    migration_wave: str


def _routing(
    evaluation: TargetEvaluation,
    *,
    effort_days: float,
    band: str,
) -> _Routing:
    """Take routing from the evaluation and recompute wave from the confirmed target."""
    return _Routing(
        recommended_target=evaluation.recommended_target,
        target_components=evaluation.target_components,
        recommendation_reason=evaluation.recommendation_reason,
        estimated_effort_days=(
            evaluation.estimated_effort_days
            if evaluation.estimated_effort_days is not None
            else effort_days
        ),
        migration_wave=(
            evaluation.migration_wave_override
            or migration_wave(evaluation.recommended_target, band)
        ),
    )


def apply_alteryx_native_route(
    path: Path,
    assessment: WorkflowAssessment,
    *,
    graph: WorkflowGraph | None = None,
) -> WorkflowAssessment:
    """Finalize Alteryx assessment routing without executing the workflow."""
    evaluation = evaluate_alteryx_native_route(
        path,
        unsupported_tools=assessment.unsupported_tools,
        default_target=assessment.recommended_target,
        default_components=assessment.target_components,
        default_reason=assessment.recommendation_reason,
        graph=graph,
    )
    routing = _routing(
        evaluation,
        effort_days=assessment.estimated_effort_days,
        band=assessment.complexity_band,
    )
    return replace(assessment, **routing._asdict())


def apply_native_route(
    package: EtlPackage,
    asset: EtlAsset,
    assessment: EtlAssessment,
) -> EtlAssessment:
    """Finalize target routing using one shared set of compiled definitions."""
    evaluation = evaluate_etl_native_route(
        package,
        asset,
        base_reason=assessment.recommendation_reason,
    )
    routing = _routing(
        evaluation,
        effort_days=assessment.estimated_effort_days,
        band=assessment.complexity_band,
    )
    return replace(assessment, **routing._asdict())


def confirm_assessment(
    assessment: WorkflowAssessmentResponse, evaluation: TargetEvaluation
) -> WorkflowAssessmentResponse:
    """Apply a confirmed Fabric evaluation to a stored static assessment.

    This is the compatibility layer for consumers that read target, wave, and effort from
    the assessment response. It never compiles anything.
    """
    routing = _routing(
        evaluation,
        effort_days=assessment.estimated_effort_days,
        band=assessment.complexity_band,
    )
    return assessment.model_copy(
        update={**routing._asdict(), "target_components": list(routing.target_components)}
    )
