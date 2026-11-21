"""Compiler-grounded target routing for canonical ETL assets."""

from dataclasses import replace
from pathlib import Path

from accelerator.assessment import WorkflowAssessment
from accelerator.effort import remaining_effort_days
from accelerator.etl_assessment import EtlAssessment
from accelerator.etl_generation import compile_asset_targets
from accelerator.etl_ir import EtlAsset, EtlPackage
from accelerator.generation import Target, generate_candidate


def apply_alteryx_native_route(path: Path, assessment: WorkflowAssessment) -> WorkflowAssessment:
    """Finalize Alteryx assessment routing without executing the workflow."""
    if (
        assessment.unsupported_tools
        and {"Dataflow Gen2", "Fabric Notebook"}.issubset(assessment.target_components)
    ):
        dataflow = generate_candidate(path, "dataflow")
        notebook = generate_candidate(path, "notebook")
        if dataflow.deployable and notebook.deployable:
            bindings = (*dataflow.required_bindings, *notebook.required_bindings)
            return replace(
                assessment,
                recommended_target="Mixed Fabric solution",
                target_components=(
                    "Dataflow Gen2",
                    "Fabric Notebook",
                    "Fabric Pipeline",
                ),
                recommendation_reason=(
                    assessment.recommendation_reason
                    + "; generated bundle orchestrates Dataflow Gen2 then Fabric Notebook"
                ),
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
        reason = assessment.recommendation_reason
        if assessment.recommended_target != label:
            reason += f"; native compiler routes deployment to {label}"
        return replace(
            assessment,
            recommended_target=label,
            target_components=(label,),
            recommendation_reason=reason,
            estimated_effort_days=remaining_effort_days(
                required_bindings=candidate.required_bindings,
            ),
        )
    return replace(
        assessment,
        recommended_target="Manual rework",
        target_components=(),
        recommendation_reason=(
            assessment.recommendation_reason
            + "; no deployable native Dataflow or Notebook implementation is available"
        ),
        migration_wave="Redesign",
    )


def apply_native_route(
    package: EtlPackage,
    asset: EtlAsset,
    assessment: EtlAssessment,
) -> EtlAssessment:
    """Finalize target routing using one shared set of compiled definitions."""
    candidates = compile_asset_targets(package, asset)
    if candidates.dataflow.deployable and candidates.pipeline.deployable:
        bindings = (
            *candidates.dataflow.required_bindings,
            *candidates.pipeline.required_bindings,
        )
        return replace(
            assessment,
            recommended_target="Mixed Fabric solution",
            target_components=("Dataflow Gen2", "Fabric Pipeline"),
            recommendation_reason=(
                assessment.recommendation_reason
                + "; native compiler emits a Dataflow and dependent Fabric Pipeline"
            ),
            estimated_effort_days=remaining_effort_days(
                required_bindings=bindings,
            ),
        )
    if candidates.notebook.deployable and candidates.pipeline.deployable:
        bindings = (
            *candidates.notebook.required_bindings,
            *candidates.pipeline.required_bindings,
        )
        return replace(
            assessment,
            recommended_target="Mixed Fabric solution",
            target_components=("Fabric Notebook", "Fabric Pipeline"),
            recommendation_reason=(
                assessment.recommendation_reason
                + "; native compiler emits a Fabric Notebook and dependent Fabric Pipeline"
            ),
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
            return replace(
                assessment,
                recommended_target=label,
                target_components=(label,),
                recommendation_reason=(
                    assessment.recommendation_reason
                    + f"; native compiler routes deployment to {label}"
                ),
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
    return replace(
        assessment,
        recommended_target="Manual rework",
        target_components=(),
        recommendation_reason=(
            assessment.recommendation_reason
            + f"; no deployable native implementation is available: {detail}"
        ),
        migration_wave="Redesign",
    )
