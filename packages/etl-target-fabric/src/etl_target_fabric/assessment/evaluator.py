"""Compiler-grounded Microsoft Fabric target-fit evaluation."""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import replace
from pathlib import Path
from typing import TYPE_CHECKING

from etl_migration_core.contracts.ir import EtlAsset, EtlPackage
from etl_migration_core.contracts.spi import TargetEvaluation
from etl_target_fabric.assessment.effort import remaining_effort_days
from etl_target_fabric.compilers.alteryx import Target, generate_candidate
from etl_target_fabric.compilers.ir import compile_asset_targets

if TYPE_CHECKING:
    from etl_target_fabric.assessment.ir_assessment import EtlAssessment
    from etl_target_fabric.assessment.workflow import WorkflowAssessment


def evaluate_alteryx_native_route(
    path: Path,
    *,
    unsupported_tools: Sequence[str],
    default_target: str,
    default_components: Sequence[str],
    default_reason: str,
) -> TargetEvaluation:
    """Evaluate Fabric target fit for an Alteryx workflow without mutating assessment."""
    if (
        unsupported_tools
        and {"Dataflow Gen2", "Fabric Notebook"}.issubset(default_components)
    ):
        dataflow = generate_candidate(path, "dataflow")
        notebook = generate_candidate(path, "notebook")
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
        candidate = generate_candidate(path, target)
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
) -> TargetEvaluation:
    """Evaluate Fabric target fit using one shared set of compiled definitions."""
    candidates = compile_asset_targets(package, asset)
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


def apply_alteryx_native_route(
    path: Path, assessment: WorkflowAssessment
) -> WorkflowAssessment:
    """Finalize Alteryx assessment routing without executing the workflow."""
    evaluation = evaluate_alteryx_native_route(
        path,
        unsupported_tools=assessment.unsupported_tools,
        default_target=assessment.recommended_target,
        default_components=assessment.target_components,
        default_reason=assessment.recommendation_reason,
    )
    return replace(
        assessment,
        recommended_target=evaluation.recommended_target,
        target_components=evaluation.target_components,
        recommendation_reason=evaluation.recommendation_reason,
        estimated_effort_days=(
            evaluation.estimated_effort_days
            if evaluation.estimated_effort_days is not None
            else assessment.estimated_effort_days
        ),
        migration_wave=(
            evaluation.migration_wave_override or assessment.migration_wave
        ),
    )


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
    return replace(
        assessment,
        recommended_target=evaluation.recommended_target,
        target_components=evaluation.target_components,
        recommendation_reason=evaluation.recommendation_reason,
        estimated_effort_days=(
            evaluation.estimated_effort_days
            if evaluation.estimated_effort_days is not None
            else assessment.estimated_effort_days
        ),
        migration_wave=(
            evaluation.migration_wave_override or assessment.migration_wave
        ),
    )
