"""Compiler-grounded target routing for canonical ETL assets."""

from dataclasses import replace

from accelerator.effort import remaining_effort_days
from accelerator.etl_assessment import EtlAssessment
from accelerator.etl_generation import compile_asset_targets
from accelerator.etl_ir import EtlAsset, EtlPackage


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
