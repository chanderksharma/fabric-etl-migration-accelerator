"""Stateless Microsoft Fabric artifact writer and bundle packager."""

from __future__ import annotations

import base64
import io
import json
import re
import uuid
import zipfile
from collections.abc import Callable, Sequence
from dataclasses import dataclass
from pathlib import Path
from typing import Literal, Protocol

from etl_migration_core.contracts.ir import SourcePlatform
from etl_target_fabric.compilers.alteryx import Candidate, Target
from etl_target_fabric.delivery.notebook_encoder import build_notebook_cells as _notebook_cells

IdentityMode = Literal["content", "asset"]


class AssessmentTargetSummary(Protocol):
    @property
    def path(self) -> str: ...

    @property
    def target_components(self) -> Sequence[str]: ...


@dataclass(frozen=True)
class ArtifactWriteResult:
    root: Path
    candidates: list[Candidate]


def write_candidates(
    *,
    run_id: str,
    target: Target,
    artifact_root: Path,
    generate_fn: Callable[[Target], list[Candidate]],
    assessments: Sequence[AssessmentTargetSummary],
    identity_mode: IdentityMode = "content",
    write_plan: bool = True,
) -> ArtifactWriteResult:
    """Persist Fabric definitions, manifests, and (optionally) the deployment plan for one run.

    ``write_plan=False`` skips compiling the other targets and the cross-target deployment
    plan; use it for previews and single-target packages that never read that plan.
    """
    if not re.fullmatch(r"[a-f0-9]{32}", run_id):
        raise ValueError("Run ID must be a 32-character lowercase hexadecimal value")
    candidates = generate_fn(target)
    identities: dict[str, str] = {}
    paths: set[str] = set()
    for candidate in candidates:
        relative = _candidate_artifact_path(candidate)
        path_key = relative.as_posix().casefold()
        if path_key in paths:
            raise ValueError(f"Workflow output path collides after sanitization: {relative}")
        paths.add(path_key)
        if candidate.validation_state in {"blocked", "scaffold"}:
            continue
        logical_id = _fabric_logical_id(candidate, identity_mode=identity_mode)
        previous = identities.get(logical_id)
        if previous is not None:
            raise ValueError(
                f"Fabric logical ID collision between {previous!r} and {candidate.workflow!r}; "
                "multiple assets from the same source need an identity migration"
            )
        identities[logical_id] = candidate.workflow
    plan_targets: tuple[Target, ...] = ("dataflow", "notebook", "pipeline")
    plan_candidates = (
        {
            plan_target: candidates if plan_target == target else generate_fn(plan_target)
            for plan_target in plan_targets
        }
        if write_plan
        else {}
    )
    resolved_root = artifact_root.resolve()
    resolved_root.mkdir(parents=True, exist_ok=True)
    _write_artifact_guide(resolved_root)
    written: list[Candidate] = []
    index: list[dict[str, object]] = []
    for position, candidate in enumerate(candidates):
        relative = _candidate_artifact_path(candidate)
        artifact_path = relative.as_posix()
        folder = (resolved_root / relative).resolve()
        if not folder.is_relative_to(resolved_root):
            raise ValueError("Workflow artifact path escapes the configured output root")
        folder.mkdir(parents=True, exist_ok=True)
        _remove_target_files(folder, target)
        if candidate.validation_state in {"blocked", "scaffold"}:
            files = [f"{target}-diagnostics.json", f"{target}-manifest.json"]
            updated = candidate.model_copy(
                update={"artifact_path": artifact_path, "definition_files": files}
            )
            _atomic_write_text(
                folder / f"{target}-diagnostics.json",
                json.dumps(
                    {
                        "workflow": candidate.workflow,
                        "state": "blocked",
                        "diagnostics": candidate.diagnostics,
                    },
                    indent=2,
                ),
            )
        else:
            definition = _local_definition_files(
                target,
                _fabric_definition(candidate, relative.name, identity_mode=identity_mode),
            )
            files = list(definition)
            updated = candidate.model_copy(
                update={"artifact_path": artifact_path, "definition_files": files}
            )
            for name, content in definition.items():
                _atomic_write_text(folder / name, content)
        _atomic_write_text(
            folder / f"{target}-manifest.json", updated.model_dump_json(indent=2)
        )
        written.append(updated)
        index.append(
            {
                "position": position,
                "workflow": updated.workflow,
                "target": updated.target,
                "state": updated.validation_state,
                "deployable_definition": updated.deployable,
                "runtime_ready": updated.runtime_ready,
                "path": updated.artifact_path,
                "files": updated.definition_files,
            }
        )
    index_name = f"artifact-index-{target}.json"
    _atomic_write_text(
        resolved_root / index_name,
        json.dumps(
            {
                "run_id": run_id,
                "target": target,
                "artifact_count": len(written),
                "generated_count": sum(item.definition_ready for item in written),
                "blocked_count": sum(not item.definition_ready for item in written),
                "artifacts": index,
            },
            indent=2,
        ),
    )
    _write_combined_index(resolved_root, run_id)
    if write_plan:
        _write_deployment_plan(
            resolved_root,
            run_id,
            plan_candidates["dataflow"],
            plan_candidates["notebook"],
            plan_candidates["pipeline"],
            assessments,
        )
    _write_latest_index(resolved_root, run_id, target, index_name)
    return ArtifactWriteResult(resolved_root, written)


def build_candidate_package(persisted: ArtifactWriteResult, target: Target) -> bytes:
    """Build a byte-stable archive from persisted Fabric definitions for one target."""
    paths = {
        persisted.root / f"artifact-index-{target}.json",
        persisted.root / "DEPLOYMENT.txt",
        persisted.root / "latest.json",
    }
    for candidate in persisted.candidates:
        if candidate.target != target:
            raise ValueError("Candidate target does not match the requested package")
        folder = (persisted.root / _candidate_artifact_path(candidate)).resolve()
        if not folder.is_relative_to(persisted.root):
            raise ValueError("Workflow artifact path escapes the configured output root")
        names = {*candidate.definition_files, f"{target}-manifest.json"}
        if not names <= _target_file_names(target):
            raise ValueError("Candidate contains unexpected artifact filenames")
        paths.update(folder / name for name in names)
    output = io.BytesIO()
    with zipfile.ZipFile(output, "w") as archive:
        for path in sorted(paths, key=lambda item: str(item).casefold()):
            entry = zipfile.ZipInfo(
                str(path.relative_to(persisted.root)).replace("\\", "/"),
                date_time=(1980, 1, 1, 0, 0, 0),
            )
            entry.compress_type = zipfile.ZIP_DEFLATED
            archive.writestr(entry, path.read_bytes())
    return output.getvalue()


def build_workflow_package(
    *,
    artifact_root: Path,
    candidates: list[Candidate],
    workflow: str,
) -> tuple[bytes, str]:
    """Build a byte-stable archive for one workflow and all generated Fabric items."""
    matched = next(
        (candidate for candidate in candidates if candidate.workflow == workflow),
        None,
    )
    if matched is None:
        raise ValueError(f"Workflow was not found in the confirmed run: {workflow}")
    relative = _candidate_artifact_path(matched)
    resolved_root = artifact_root.resolve()
    folder = (resolved_root / relative).resolve()
    if not folder.is_relative_to(resolved_root) or not folder.is_dir():
        raise ValueError("Workflow artifact folder is unavailable")
    output = io.BytesIO()
    with zipfile.ZipFile(output, "w") as archive:
        for path in sorted(folder.iterdir(), key=lambda item: item.name.casefold()):
            if not path.is_file() or not _belongs_to_workflow_bundle(path.name):
                continue
            entry = zipfile.ZipInfo(
                path.name,
                date_time=(1980, 1, 1, 0, 0, 0),
            )
            entry.compress_type = zipfile.ZIP_DEFLATED
            archive.writestr(entry, path.read_bytes())
    return output.getvalue(), f"{relative.name}-fabric-bundle.zip"


def _artifact_path(workflow: str) -> Path:
    parts = [part for part in re.split(r"[\\/!]+", workflow) if part]
    if not parts:
        return Path("workflow")
    parts[-1] = Path(parts[-1]).stem
    clean = [re.sub(r"[^A-Za-z0-9_-]+", "-", part).strip("-")[:80] or "workflow" for part in parts]
    return Path(*clean)


def _candidate_artifact_path(candidate: Candidate) -> Path:
    if candidate.source_platform is SourcePlatform.ALTERYX:
        return _artifact_path(candidate.workflow)
    platform_root = {
        SourcePlatform.INFORMATICA_POWERCENTER: "informatica-powercenter",
        SourcePlatform.INFORMATICA_IDMC: "informatica-idmc",
    }.get(
        candidate.source_platform,
        re.sub(r"[^A-Za-z0-9-]+", "-", str(candidate.source_platform)).strip("-") or "source",
    )
    asset_name = candidate.native_id or candidate.workflow.rsplit("!", 1)[-1]
    return Path(platform_root) / _artifact_path(asset_name)


def _fabric_logical_id(
    candidate: Candidate, *, identity_mode: IdentityMode = "content"
) -> str:
    if identity_mode == "asset":
        asset_key = candidate.native_id or _candidate_artifact_path(candidate).as_posix()
        return str(
            uuid.uuid5(
                uuid.NAMESPACE_URL,
                f"{candidate.target}:{candidate.source_platform}:{asset_key}",
            )
        )
    return str(uuid.uuid5(uuid.NAMESPACE_URL, f"{candidate.target}:{candidate.source_sha256}"))


def build_logical_id_migration_plan(
    candidates: Sequence[Candidate],
) -> list[dict[str, str]]:
    """Produce a deterministic mapping from legacy content IDs to stable asset IDs."""
    return [
        {
            "workflow": candidate.workflow,
            "target": candidate.target,
            "legacy_logical_id": _fabric_logical_id(candidate, identity_mode="content"),
            "stable_logical_id": _fabric_logical_id(candidate, identity_mode="asset"),
        }
        for candidate in candidates
        if candidate.validation_state not in {"blocked", "scaffold"}
    ]


def _fabric_definition(
    candidate: Candidate,
    slug: str,
    *,
    identity_mode: IdentityMode = "content",
) -> dict[str, str]:
    display_name = Path(candidate.workflow.replace("!", "/")).stem[:120] or slug
    logical_id = _fabric_logical_id(candidate, identity_mode=identity_mode)
    source_label = (
        "Alteryx"
        if candidate.source_platform is SourcePlatform.ALTERYX
        else candidate.source_product
    )
    description = (
        f"Generated from {source_label} static analysis. "
        "Independent semantic validation remains required."
    )
    platform = {
        "$schema": (
            "https://developer.microsoft.com/json-schemas/fabric/"
            "gitIntegration/platformProperties/2.0.0/schema.json"
        ),
        "metadata": {
            "type": {
                "notebook": "Notebook",
                "dataflow": "Dataflow",
                "pipeline": "DataPipeline",
            }[candidate.target],
            "displayName": display_name,
            "description": description,
        },
        "config": {"version": "2.0", "logicalId": logical_id},
    }
    platform_text = json.dumps(platform, indent=2, sort_keys=True)
    if candidate.target == "pipeline":
        request = {
            "displayName": display_name,
            "type": "DataPipeline",
            "description": description,
            "definition": {
                "parts": [
                    _definition_part("pipeline-content.json", candidate.code),
                    _definition_part(".platform", platform_text),
                ]
            },
        }
        return {
            "pipeline-content.json": candidate.code,
            ".platform": platform_text,
            "create-item.json": json.dumps(request, indent=2, sort_keys=True),
        }

    if candidate.target == "notebook":
        notebook = {
            "nbformat": 4,
            "nbformat_minor": 5,
            "metadata": {
                "kernelspec": {
                    "display_name": "Synapse PySpark",
                    "language": "Python",
                    "name": "synapse_pyspark",
                },
                "language_info": {"name": "python"},
            },
            "cells": _notebook_cells(candidate, display_name),
        }
        notebook_text = json.dumps(notebook, indent=2, sort_keys=True)
        request = {
            "displayName": display_name,
            "type": "Notebook",
            "description": description,
            "definition": {
                "format": "ipynb",
                "parts": [
                    _definition_part("notebook-content.ipynb", notebook_text),
                    _definition_part(".platform", platform_text),
                ],
            },
        }
        return {
            "notebook-content.ipynb": notebook_text,
            ".platform": platform_text,
            "create-item.json": json.dumps(request, indent=2, sort_keys=True),
        }

    query_name = re.sub(r"[^A-Za-z0-9_]+", "_", display_name).strip("_") or "MigratedWorkflow"
    if candidate.definition_queries:
        mashup = candidate.code
        query_names = candidate.definition_queries
    else:
        mashup = (
            f"section Section1;\n"
            f"shared #{_m_identifier(query_name)} = {candidate.code.strip()};\n"
        )
        query_names = [query_name]
    metadata = {
        "formatVersion": "202502",
        "computeEngineSettings": {"allowFastCopy": False},
        "name": display_name,
        "queryGroups": [
            {
                "id": group.id,
                "name": group.name,
                "description": group.description,
                "parentId": group.parent_id,
                "order": group.order,
            }
            for group in candidate.query_groups
        ],
        "queriesMetadata": {
            name: {
                "queryId": str(
                    uuid.uuid5(
                        uuid.NAMESPACE_URL,
                        f"query:{candidate.source_sha256}:{name}",
                    )
                ),
                "queryName": name,
                **(
                    {"queryGroupId": candidate.query_group_assignments[name]}
                    if name in candidate.query_group_assignments
                    else {}
                ),
                "loadEnabled": False,
            }
            for name in query_names
        },
        "connections": [],
    }
    metadata_text = json.dumps(metadata, indent=2, sort_keys=True)
    request = {
        "displayName": display_name,
        "type": "Dataflow",
        "description": description,
        "definition": {
            "parts": [
                _definition_part("mashup.pq", mashup),
                _definition_part("queryMetadata.json", metadata_text),
                _definition_part(".platform", platform_text),
            ]
        },
    }
    return {
        "mashup.pq": mashup,
        "queryMetadata.json": metadata_text,
        ".platform": platform_text,
        "create-item.json": json.dumps(request, indent=2, sort_keys=True),
    }


def _definition_part(path: str, content: str) -> dict[str, str]:
    return {
        "path": path,
        "payload": base64.b64encode(content.encode("utf-8")).decode("ascii"),
        "payloadType": "InlineBase64",
    }


def _write_latest_index(
    artifact_root: Path, identity: str, target: Target, index_name: str
) -> None:
    latest = artifact_root / "latest.json"
    content: dict[str, object] = {"run_id": identity, "targets": {}}
    if latest.is_file():
        existing = json.loads(latest.read_text(encoding="utf-8"))
        if isinstance(existing, dict) and existing.get("run_id") == identity:
            content = existing
    targets = content.get("targets")
    if not isinstance(targets, dict):
        targets = {}
        content["targets"] = targets
    targets[target] = index_name
    _atomic_write_text(latest, json.dumps(content, indent=2))


def _write_artifact_guide(artifact_root: Path) -> None:
    _atomic_write_text(
        artifact_root / "DEPLOYMENT.txt",
        "Fabric definition output\n"
        "========================\n\n"
        "Open latest.json to see which assessment run produced the current definitions.\n"
        "Each workflow directory contains target-prefixed Notebook and Dataflow files.\n"
        "The *-create-item.json files are complete Fabric Create Item request bodies.\n"
        "Blocked targets contain *-diagnostics.json and are not deployable definitions.\n\n"
        "Submit definitions only to an approved\n"
        "development workspace with authorized identity and after reviewing source bindings.\n"
        "Generated definitions are unvalidated until source/target semantic parity is accepted.\n"
        "For a new Dataflow, use ApplyChangesIfNeeded on the first refresh after "
        "definition save.\n",
    )


def _local_definition_files(target: Target, definition: dict[str, str]) -> dict[str, str]:
    names = {
        "notebook": {
            "notebook-content.ipynb": "notebook-content.ipynb",
            ".platform": "notebook.platform.json",
            "create-item.json": "notebook-create-item.json",
        },
        "dataflow": {
            "mashup.pq": "dataflow-mashup.pq",
            "queryMetadata.json": "dataflow-queryMetadata.json",
            ".platform": "dataflow.platform.json",
            "create-item.json": "dataflow-create-item.json",
        },
        "pipeline": {
            "pipeline-content.json": "pipeline-content.json",
            ".platform": "pipeline.platform.json",
            "create-item.json": "pipeline-create-item.json",
        },
    }[target]
    return {names[name]: content for name, content in definition.items()}


def _target_file_names(target: Target) -> set[str]:
    names = {f"{target}-manifest.json", f"{target}-diagnostics.json"}
    if target == "notebook":
        return names | {
            "notebook-content.ipynb",
            "notebook.platform.json",
            "notebook-create-item.json",
        }
    if target == "pipeline":
        return names | {
            "pipeline-content.json",
            "pipeline.platform.json",
            "pipeline-create-item.json",
        }
    return names | {
        "dataflow-mashup.pq",
        "dataflow-queryMetadata.json",
        "dataflow.platform.json",
        "dataflow-create-item.json",
    }


def _remove_target_files(folder: Path, target: Target) -> None:
    for name in _target_file_names(target):
        path = folder / name
        if path.is_file():
            path.unlink()


def _write_combined_index(root: Path, run_id: str) -> None:
    targets: dict[str, object] = {}
    for target in ("notebook", "dataflow", "pipeline"):
        path = root / f"artifact-index-{target}.json"
        if path.is_file():
            payload = json.loads(path.read_text(encoding="utf-8"))
            if payload.get("run_id") == run_id:
                targets[target] = payload
    _atomic_write_text(
        root / "artifact-index.json",
        json.dumps({"run_id": run_id, "targets": targets}, indent=2),
    )


def _pipeline_definition(candidate: Candidate, display_name: str) -> dict[str, str]:
    pipeline_name = f"{display_name}_Orchestration"
    description = (
        f"Orchestrates generated Dataflow Gen2 and Fabric Notebook for "
        f"{display_name}."
    )
    content = {
        "properties": {
            "activities": [
                {
                    "type": "RefreshDataflow",
                    "typeProperties": {
                        "dataflowId": "{{DATAFLOW_ITEM_ID}}",
                        "workspaceId": "{{WORKSPACE_ID}}",
                        "notifyOption": "NoNotification",
                    },
                    "policy": {
                        "timeout": "0.12:00:00",
                        "retry": 0,
                        "retryIntervalInSeconds": 30,
                        "secureInput": False,
                        "secureOutput": False,
                    },
                    "name": "Run Dataflow Gen2",
                    "dependsOn": [],
                },
                {
                    "type": "TridentNotebook",
                    "typeProperties": {
                        "notebookId": "{{NOTEBOOK_ITEM_ID}}",
                        "workspaceId": "{{WORKSPACE_ID}}",
                        "parameters": {},
                    },
                    "policy": {
                        "timeout": "0.12:00:00",
                        "retry": 0,
                        "retryIntervalInSeconds": 30,
                        "secureInput": False,
                        "secureOutput": False,
                    },
                    "name": "Run Fabric Notebook",
                    "dependsOn": [
                        {
                            "activity": "Run Dataflow Gen2",
                            "dependencyConditions": ["Succeeded"],
                        }
                    ],
                },
            ]
        }
    }
    platform = {
        "$schema": (
            "https://developer.microsoft.com/json-schemas/fabric/"
            "gitIntegration/platformProperties/2.0.0/schema.json"
        ),
        "metadata": {
            "type": "DataPipeline",
            "displayName": pipeline_name,
            "description": description,
        },
        "config": {
            "version": "2.0",
            "logicalId": str(
                uuid.uuid5(
                    uuid.NAMESPACE_URL,
                    f"pipeline:{candidate.source_sha256}:{pipeline_name}",
                )
            ),
        },
    }
    content_text = json.dumps(content, indent=2, sort_keys=True)
    platform_text = json.dumps(platform, indent=2, sort_keys=True)
    request = {
        "displayName": pipeline_name,
        "type": "DataPipeline",
        "description": description,
        "definition": {
            "parts": [
                _definition_part("pipeline-content.json", content_text),
                _definition_part(".platform", platform_text),
            ]
        },
    }
    bundle = {
        "schemaVersion": "1.0",
        "workflow": candidate.workflow,
        "deploymentOrder": ["Dataflow", "Notebook", "DataPipeline"],
        "items": [
            {
                "key": "dataflow",
                "type": "Dataflow",
                "request": "dataflow-create-item.json",
            },
            {
                "key": "notebook",
                "type": "Notebook",
                "request": "notebook-create-item.json",
            },
            {
                "key": "pipeline",
                "type": "DataPipeline",
                "request": "pipeline-create-item.json",
                "dependsOn": ["dataflow", "notebook"],
            },
        ],
    }
    return {
        "pipeline-content.json": content_text,
        "pipeline.platform.json": platform_text,
        "pipeline-create-item.json": json.dumps(request, indent=2, sort_keys=True),
        "deployment-bundle.json": json.dumps(bundle, indent=2, sort_keys=True),
    }


def _write_deployment_plan(
    root: Path,
    run_id: str,
    dataflows: list[Candidate],
    notebooks: list[Candidate],
    pipelines: list[Candidate],
    assessments: Sequence[AssessmentTargetSummary],
) -> None:
    notebook_by_workflow = {candidate.workflow: candidate for candidate in notebooks}
    pipeline_by_workflow = {candidate.workflow: candidate for candidate in pipelines}
    assessment_by_workflow = {assessment.path: assessment for assessment in assessments}
    workflows: list[dict[str, object]] = []
    for dataflow in dataflows:
        notebook = notebook_by_workflow.get(dataflow.workflow)
        pipeline = pipeline_by_workflow.get(dataflow.workflow)
        artifact_path = _candidate_artifact_path(dataflow).as_posix()
        folder = root / Path(*artifact_path.split("/"))
        dataflow_available = dataflow.deployable and (
            folder / "dataflow-create-item.json"
        ).is_file()
        notebook_available = bool(
            notebook
            and notebook.deployable
            and (folder / "notebook-create-item.json").is_file()
        )
        pipeline_available = bool(
            pipeline
            and pipeline.deployable
            and (folder / "pipeline-create-item.json").is_file()
        )
        assessment = assessment_by_workflow.get(dataflow.workflow)
        target_components = set(assessment.target_components) if assessment else set()
        bundle_targets = [
            target
            for component, target in (
                ("Dataflow Gen2", "dataflow"),
                ("Fabric Notebook", "notebook"),
                ("Fabric Pipeline", "pipeline"),
            )
            if component in target_components
        ]
        bundle_required = len(bundle_targets) > 1 and "pipeline" in bundle_targets
        pipeline_files: list[str] = []
        if (
            bundle_required
            and "notebook" in bundle_targets
            and dataflow_available
            and notebook_available
        ):
            pipeline_definition = _pipeline_definition(dataflow, Path(artifact_path).name)
            for name, content in pipeline_definition.items():
                _atomic_write_text(folder / name, content)
            pipeline_files = list(pipeline_definition)
        elif pipeline_available:
            pipeline_files = [
                "pipeline-content.json",
                "pipeline.platform.json",
                "pipeline-create-item.json",
            ]
        else:
            for name in (
                "pipeline-content.json",
                "pipeline.platform.json",
                "pipeline-create-item.json",
                "deployment-bundle.json",
            ):
                path = folder / name
                if path.is_file():
                    path.unlink()
        selected = (
            dataflow
            if dataflow_available
            else notebook
            if notebook_available
            else pipeline
            if pipeline_available
            else None
        )
        component: dict[str, object] | None = None
        selected_components: list[dict[str, object]] = []
        bundle_ready = bool(
            bundle_required
            and pipeline_files
            and ("dataflow" not in bundle_targets or dataflow_available)
            and ("notebook" not in bundle_targets or notebook_available)
        )
        if bundle_ready:
            component_definitions: dict[str, dict[str, object]] = {
                "dataflow": {
                    "type": "Dataflow",
                    "target": "dataflow",
                    "path": artifact_path,
                    "definition_files": [
                        "dataflow-mashup.pq",
                        "dataflow-queryMetadata.json",
                        "dataflow.platform.json",
                        "dataflow-create-item.json",
                    ],
                },
                "notebook": {
                    "type": "Notebook",
                    "target": "notebook",
                    "path": artifact_path,
                    "definition_files": [
                        "notebook-content.ipynb",
                        "notebook.platform.json",
                        "notebook-create-item.json",
                    ],
                },
                "pipeline": {
                    "type": "DataPipeline",
                    "target": "pipeline",
                    "path": artifact_path,
                    "definition_files": pipeline_files,
                },
            }
            selected_components = [
                component_definitions[target] for target in bundle_targets
            ]
            bundle = {
                "schemaVersion": "1.0",
                "workflow": dataflow.workflow,
                "deploymentOrder": [
                    component_definitions[target]["type"] for target in bundle_targets
                ],
                "items": [
                    {
                        "key": target,
                        "type": component_definitions[target]["type"],
                        "request": f"{target}-create-item.json",
                        **(
                            {
                                "dependsOn": [
                                    dependency
                                    for dependency in bundle_targets
                                    if dependency != "pipeline"
                                ]
                            }
                            if target == "pipeline"
                            else {}
                        ),
                    }
                    for target in bundle_targets
                ],
            }
            _atomic_write_text(
                folder / "deployment-bundle.json",
                json.dumps(bundle, indent=2, sort_keys=True),
            )
            if "deployment-bundle.json" not in pipeline_files:
                pipeline_files.append("deployment-bundle.json")
        elif selected is not None:
            component = {
                "type": {
                    "dataflow": "Dataflow",
                    "notebook": "Notebook",
                    "pipeline": "DataPipeline",
                }[selected.target],
                "target": selected.target,
                "path": artifact_path,
                "definition_files": (
                    [
                        "dataflow-mashup.pq",
                        "dataflow-queryMetadata.json",
                        "dataflow.platform.json",
                        "dataflow-create-item.json",
                    ]
                    if selected.target == "dataflow"
                    else [
                        "notebook-content.ipynb",
                        "notebook.platform.json",
                        "notebook-create-item.json",
                    ]
                    if selected.target == "notebook"
                    else pipeline_files
                ),
            }
            selected_components = [component]
        diagnostics = [
            *[f"dataflow: {message}" for message in dataflow.diagnostics],
            *(
                [f"notebook: {message}" for message in notebook.diagnostics]
                if notebook
                else ["notebook: candidate missing"]
            ),
            *(
                [f"pipeline: {message}" for message in pipeline.diagnostics]
                if pipeline
                else ["pipeline: candidate missing"]
            ),
        ]
        workflow_entry: dict[str, object] = {
            "workflow": dataflow.workflow,
            "artifact_path": artifact_path,
            "status": "native_ready" if selected_components else "compiler_required",
            "routing_order": ["dataflow", "notebook", "pipeline"],
            "selected_components": selected_components,
            "pipeline_required": bundle_required,
            "diagnostics": diagnostics if not selected_components else [],
        }
        workflows.append(workflow_entry)
        _atomic_write_text(
            folder / "README.md",
            _workflow_bundle_readme(workflow_entry, folder),
        )
    _atomic_write_text(
        root / "deployment-plan.json",
        json.dumps(
            {
                "run_id": run_id,
                "routing_policy": "Dataflow Gen2, then Fabric Notebook, then Pipeline/mix",
                "workflow_count": len(workflows),
                "native_ready_count": sum(
                    workflow["status"] == "native_ready" for workflow in workflows
                ),
                "compiler_required_count": sum(
                    workflow["status"] == "compiler_required" for workflow in workflows
                ),
                "workflows": workflows,
            },
            indent=2,
        ),
    )


def _workflow_bundle_readme(workflow: dict[str, object], folder: Path) -> str:
    source = str(workflow["workflow"])
    display_name = _artifact_path(source).name
    status = str(workflow["status"])
    files = sorted(
        (
            path.name
            for path in folder.iterdir()
            if path.is_file()
            and path.name != "README.md"
            and _belongs_to_workflow_bundle(path.name)
        ),
        key=str.casefold,
    )
    file_rows = [
        f"| `{name}` | {_bundle_file_description(name)} |"
        for name in files
    ]
    request_files = [
        name
        for name in (
            "dataflow-create-item.json",
            "notebook-create-item.json",
            "pipeline-create-item.json",
        )
        if name in files
    ]
    deployment_commands = []
    for request_file in request_files:
        deployment_commands.extend(
            [
                f"# Create the item described by {request_file}",
                "az rest --method post `",
                '  --resource "https://api.fabric.microsoft.com" `',
                '  --url "https://api.fabric.microsoft.com/v1/workspaces/'
                '$WorkspaceId/items" `',
                '  --headers "Content-Type=application/json" `',
                f'  --body "@{request_file}"',
                "",
            ]
        )
    if not deployment_commands:
        deployment_commands = [
            "# No deployable create-item envelope is available.",
            "# Review the diagnostics files and complete the missing implementation.",
        ]
    pipeline_note = ""
    if "pipeline-create-item.json" in files:
        dependencies = [
            label
            for filename, label in (
                ("dataflow-create-item.json", "Dataflow"),
                ("notebook-create-item.json", "Notebook"),
            )
            if filename in files
        ]
        dependency_summary = " and ".join(dependencies) or "compute items"
        placeholders = ["`{{WORKSPACE_ID}}`"]
        if "dataflow-create-item.json" in files:
            placeholders.append("`{{DATAFLOW_ITEM_ID}}`")
        if "notebook-create-item.json" in files:
            placeholders.append("`{{NOTEBOOK_ITEM_ID}}`")
        pipeline_note = f"""
### Pipeline dependency IDs

Deploy the {dependency_summary} first. Capture the returned item IDs, replace
{", ".join(placeholders)} in
`pipeline-content.json`, then rebuild the `pipeline-content.json` Base64 payload
inside `pipeline-create-item.json` before creating the pipeline.
"""
    diagnostics = workflow.get("diagnostics")
    diagnostic_lines = (
        [f"- {value}" for value in diagnostics]
        if isinstance(diagnostics, list) and diagnostics
        else ["- No compiler diagnostics were recorded."]
    )
    return "\n".join(
        [
            f"# {display_name} Fabric workflow bundle",
            "",
            f"Source workflow: `{source}`",
            "",
            f"Generation status: `{status}`",
            "",
            "> [!IMPORTANT]",
            "> Independent semantic validation remains required. Generated definitions",
            "> can be structurally deployable while source connections, destinations,",
            "> credentials, schemas, and business parity still require configuration.",
            "",
            "## Bundle contents",
            "",
            "| File | Purpose |",
            "| --- | --- |",
            *file_rows,
            "",
            "## Manual deployment",
            "",
            "### Prerequisites",
            "",
            "- PowerShell 7 and Azure CLI.",
            "- A Microsoft Fabric workspace on active capacity.",
            "- Contributor or higher permission on the target workspace.",
            "- Permission to create the included Fabric item types.",
            "- Approved source connections and destination items.",
            "",
            "### Authenticate and select the workspace",
            "",
            "```powershell",
            "az login",
            '$WorkspaceId = "<fabric-workspace-guid>"',
            "```",
            "",
            "### Configure bindings before deployment",
            "",
            "Review the decoded definition files before using the request envelopes.",
            "Dataflow source and destination bindings are intentionally unresolved when",
            "workspace connection IDs cannot be inferred. Notebook `source_paths` values",
            "must be completed before execution. If a decoded definition changes, update",
            "the matching Base64 part in its `*-create-item.json` envelope.",
            "",
            "### Create the generated items",
            "",
            "Run the following commands from this extracted bundle directory. Create",
            "items in Dataflow, Notebook, then Data Pipeline order when all are present.",
            "",
            "```powershell",
            *deployment_commands,
            "```",
            pipeline_note.strip(),
            "",
            "## Post-deployment verification",
            "",
            "1. Open each created item in the Fabric workspace.",
            "2. Configure and test source connections and destination bindings.",
            "3. Run source previews before the first full execution.",
            "4. Compare schemas, row counts, null behavior, and business calculations",
            "   with the Alteryx workflow.",
            "5. Promote only after independent parity and operational validation.",
            "",
            "## Compiler diagnostics",
            "",
            *diagnostic_lines,
            "",
        ]
    )


def _bundle_file_description(name: str) -> str:
    descriptions = {
        "dataflow-mashup.pq": "Power Query M transformations.",
        "dataflow-queryMetadata.json": "Dataflow queries, groups, loads, and connections.",
        "dataflow.platform.json": "Dataflow Fabric item metadata.",
        "dataflow-create-item.json": "Fabric REST create-item request for the Dataflow.",
        "notebook-content.ipynb": "Documented Fabric PySpark notebook.",
        "notebook.platform.json": "Notebook Fabric item metadata.",
        "notebook-create-item.json": "Fabric REST create-item request for the Notebook.",
        "pipeline-content.json": "Fabric Data Pipeline activity definition.",
        "pipeline.platform.json": "Pipeline Fabric item metadata.",
        "pipeline-create-item.json": "Fabric REST create-item request for the pipeline.",
        "deployment-bundle.json": "Deployment order and item dependencies.",
    }
    if name in descriptions:
        return descriptions[name]
    if name.endswith("-manifest.json"):
        return "Generated candidate status, bindings, and diagnostics."
    if name.endswith("-diagnostics.json"):
        return "Compiler blockers that require implementation."
    return "Generated workflow artifact."


def _atomic_write_text(path: Path, content: str) -> None:
    temporary = path.with_name(f".{path.name}.{uuid.uuid4().hex}.tmp")
    temporary.write_text(content, encoding="utf-8")
    temporary.replace(path)


def _belongs_to_workflow_bundle(name: str) -> bool:
    return (
        name == "README.md"
        or name == "deployment-bundle.json"
        or name.startswith(("dataflow-", "notebook-", "pipeline-"))
        or name
        in {
            "dataflow.platform.json",
            "notebook.platform.json",
            "pipeline.platform.json",
        }
    )


def _m_identifier(value: str) -> str:
    return '"' + value.replace("#", "#(#)").replace('"', '""') + '"'
