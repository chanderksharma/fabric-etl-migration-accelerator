"""Standalone tests for the etl-target-fabric PyPI package."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from etl_migration_core.contracts.ir import EXTENSIBLE_SOURCE_IR_VERSION, EtlPackage
from etl_migration_core.sources.defaults import create_default_registry
from etl_target_fabric.compilers.alteryx import Candidate, Target, generate_candidate
from etl_target_fabric.compilers.ir import compile_asset, compile_asset_targets
from etl_target_fabric.delivery.artifact_writer import write_candidates
from etl_target_fabric.delivery.deployer import dry_run
from etl_target_fabric.provider import FabricTargetProvider
from etl_target_fabric.stdio import main as fabric_stdio_main


def test_fabric_provider_artifact_writer_and_stdio(tmp_path: Path) -> None:
    sample = Path(__file__).parents[3] / "alteryx-workflows" / "sample_alteryx_workflow.yxmd"
    provider = FabricTargetProvider()
    info = provider.info()
    assert info.platform_id == "fabric"
    assert info.implemented is True
    assert "codegen" in info.capabilities

    source_reg = create_default_registry(load_entry_points=False)
    detected = source_reg.detect(sample, sample.name)
    package = source_reg.parse(sample, detected.match)
    evaluation = provider.evaluator().evaluate_asset(
        package,
        package.assets[0],
        base_reason="Static test",
    )
    assert evaluation.platform_id == "fabric"
    assert evaluation.implemented is True

    result = write_candidates(
        run_id="0123456789abcdef0123456789abcdef",
        target="notebook",
        artifact_root=tmp_path / "out",
        generate_fn=lambda target: [generate_candidate(sample, target)],
        assessments=[],
    )
    assert len(result.candidates) == 1
    assert (result.root / "latest.json").is_file()

    plan = dry_run(
        result.candidates,
        approved_workspace="ws-dev",
        requested_workspace="ws-dev",
    )
    assert plan.workspace == "ws-dev"

    assert fabric_stdio_main(["compile", str(sample), "--target", "dataflow"]) == 0
    assert fabric_stdio_main(["evaluate", str(sample)]) == 0
    assert json.loads(info.model_dump_json())["status"] == "ready"


def test_fabric_rejects_unsupported_ir_for_evaluation_and_compilation() -> None:
    sample = Path(__file__).parents[3] / "alteryx-workflows" / "sample_alteryx_workflow.yxmd"
    registry = create_default_registry(load_entry_points=False)
    detected = registry.detect(sample, sample.name)
    parsed = registry.parse(sample, detected.match)
    payload = parsed.model_dump()
    payload["ir_version"] = "99.0.0"
    package = EtlPackage.model_validate(payload)
    asset = package.assets[0]

    with pytest.raises(ValueError, match="does not support IR version"):
        FabricTargetProvider().evaluator().evaluate_asset(package, asset, base_reason="test")
    with pytest.raises(ValueError, match="does not support IR version"):
        compile_asset(package, asset, "pipeline")
    with pytest.raises(ValueError, match="does not support IR version"):
        compile_asset_targets(package, asset)


def test_fabric_rejects_uncertified_source_for_evaluation_and_compilation() -> None:
    sample = Path(__file__).parents[3] / "alteryx-workflows" / "sample_alteryx_workflow.yxmd"
    registry = create_default_registry(load_entry_points=False)
    detected = registry.detect(sample, sample.name)
    payload = registry.parse(sample, detected.match).model_dump()
    payload["source_platform"] = "ssis"
    payload["ir_version"] = EXTENSIBLE_SOURCE_IR_VERSION
    package = EtlPackage.model_validate(payload)
    asset = package.assets[0]

    with pytest.raises(ValueError, match="does not support source"):
        FabricTargetProvider().evaluator().evaluate_asset(package, asset, base_reason="test")
    with pytest.raises(ValueError, match="does not support source"):
        compile_asset(package, asset, "pipeline")


def test_artifact_writer_reuses_candidates_for_deployment_plan(tmp_path: Path) -> None:
    sample = Path(__file__).parents[3] / "alteryx-workflows" / "sample_alteryx_workflow.yxmd"
    calls: list[str] = []

    def generate(target: Target) -> list[Candidate]:
        calls.append(target)
        return [generate_candidate(sample, target)]

    write_candidates(
        run_id="0123456789abcdef0123456789abcdef",
        target="notebook",
        artifact_root=tmp_path / "out",
        generate_fn=generate,
        assessments=[],
    )

    assert sorted(calls) == ["dataflow", "notebook", "pipeline"]


def test_artifact_writer_rejects_logical_id_collision_before_writing(tmp_path: Path) -> None:
    sample = Path(__file__).parents[3] / "alteryx-workflows" / "02_low_west_sample.yxmd"
    first = generate_candidate(sample, "dataflow")
    assert first.validation_state == "generated_unvalidated"
    second = first.model_copy(update={"workflow": "different-asset.yxmd"})
    root = tmp_path / "out"

    with pytest.raises(ValueError, match="Fabric logical ID collision"):
        write_candidates(
            run_id="0123456789abcdef0123456789abcdef",
            target="dataflow",
            artifact_root=root,
            generate_fn=lambda _target: [first, second],
            assessments=[],
        )
    assert not root.exists()
