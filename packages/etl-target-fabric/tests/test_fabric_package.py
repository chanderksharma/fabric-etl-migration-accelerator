"""Standalone tests for the etl-target-fabric PyPI package."""

from __future__ import annotations

import json
from pathlib import Path

from etl_migration_core.sources.defaults import create_default_registry
from etl_target_fabric.compilers.alteryx import generate_candidate
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
