"""Resolve which generated Fabric artifact a CI deployment dispatch should use."""

from __future__ import annotations

from contextlib import nullcontext
from pathlib import Path
from typing import Literal

from fastapi import HTTPException

from accelerator.delivery.provenance import PublicationDispatch
from accelerator.runtime.runs import ArtifactWriteResult, RunService
from etl_target_fabric.compilers.alteryx import Candidate, Target

DeploymentTarget = Literal["notebook", "dataflow", "pipeline", "bundle"]
_DEPLOYMENT_TARGETS = {"notebook", "dataflow", "pipeline", "bundle"}
_ROUTING_ORDER: tuple[Target, ...] = ("dataflow", "notebook", "pipeline")


def _require_run(service: RunService, identity: str) -> None:
    try:
        service.get_run(identity, include_result=False)
    except KeyError as error:
        raise HTTPException(status_code=404, detail=str(error)) from error


def plan_deployment_dispatch(
    service: RunService,
    identity: str,
    source_workflow: str,
    requested_target: DeploymentTarget,
    *,
    isolate_local_artifacts: bool,
    publication_digest: str | None,
) -> tuple[DeploymentTarget, str, PublicationDispatch | None]:
    """Pick the artifact to dispatch, binding it to a verified publication when one is named."""
    if publication_digest is None:
        _, target, path = resolve_deployment_artifact(
            service,
            identity,
            source_workflow,
            requested_target,
            isolate_local_artifacts=isolate_local_artifacts,
        )
        return target, path, None
    _require_run(service, identity)
    try:
        with service.stage_all_artifacts(identity) as results:
            manifest_hash = service.verify_staged_publication(
                identity, publication_digest, results["dataflow"].root
            )
            _, target, path = resolve_generated_artifact(
                results, source_workflow, requested_target
            )
            return (
                target,
                path,
                PublicationDispatch(
                    artifact_root=f"published-fabric-workflows/{identity}/{publication_digest}",
                    manifest_sha256=manifest_hash,
                ),
            )
    except (OSError, ValueError) as error:
        raise HTTPException(status_code=409, detail=str(error)) from error


def resolve_deployment_artifact(
    service: RunService,
    identity: str,
    source_workflow: str,
    requested_target: DeploymentTarget,
    *,
    isolate_local_artifacts: bool = False,
) -> tuple[Candidate, DeploymentTarget, str]:
    """Generate the run's artifacts (isolated or shared) and resolve the requested one."""
    _require_run(service, identity)
    try:
        staged = (
            service.stage_all_artifacts(identity)
            if isolate_local_artifacts
            else nullcontext(service.write_all_artifacts(identity))
        )
        with staged as results:
            return resolve_generated_artifact(results, source_workflow, requested_target)
    except (OSError, ValueError) as error:
        raise HTTPException(status_code=409, detail=str(error)) from error


def resolve_generated_artifact(
    results: dict[Target, ArtifactWriteResult],
    source_workflow: str,
    requested_target: DeploymentTarget,
) -> tuple[Candidate, DeploymentTarget, str]:
    """Choose a deployable native candidate, falling back to the documented routing order."""
    candidate: Candidate | None = None
    selected_target: DeploymentTarget | None = None
    diagnostics: list[str] = []
    candidates_by_target: dict[Target, Candidate] = {}
    for target in _ROUTING_ORDER:
        written = results[target]
        current = next(
            (
                item
                for item in written.candidates
                if item.workflow == source_workflow and item.target == target
            ),
            None,
        )
        if current is None:
            continue
        candidates_by_target[target] = current
        diagnostics.extend(f"{target}: {message}" for message in current.diagnostics[:3])
        if requested_target == "bundle":
            continue
        if requested_target != target:
            continue
        if current.deployable and current.artifact_path:
            candidate = current
            selected_target = target
            break
    if requested_target == "bundle":
        deployable = [
            item
            for item in candidates_by_target.values()
            if item.deployable and item.artifact_path
        ]
        artifact_paths = {item.artifact_path for item in deployable}
        if len(artifact_paths) == 1:
            artifact_path = next(iter(artifact_paths))
            assert artifact_path is not None
            folder = results["dataflow"].root / Path(*artifact_path.split("/"))
            if (folder / "deployment-bundle.json").is_file():
                candidate = deployable[0]
                selected_target = "bundle"
    if candidate is None or selected_target is None:
        raise HTTPException(
            status_code=409,
            detail=(
                "No requested native Fabric implementation is available."
                + (f" Diagnostics: {'; '.join(diagnostics)}." if diagnostics else "")
            ),
        )
    artifact_path = candidate.artifact_path
    if artifact_path is None:
        raise HTTPException(status_code=409, detail="Selected native artifact has no path")
    if selected_target not in _DEPLOYMENT_TARGETS:
        raise HTTPException(status_code=500, detail="Resolved deployment target is invalid")
    return candidate, selected_target, artifact_path
