"""Phase 2 architecture tests: enriched Alteryx IR, Expression AST, SPI capabilities, pagination."""

from __future__ import annotations

from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from accelerator.runtime.runs import RunService
from accelerator.runtime.store import RunStore, RunStoreProtocol
from accelerator.server.api import app
from etl_migration_core.contracts.ir import SourcePlatform
from etl_migration_core.contracts.spi import (
    TargetArtifact,
    TargetDeploymentSpec,
    TargetValidationResult,
    UnsupportedTargetCapabilityError,
)
from etl_migration_core.sources.alteryx import AlteryxSourceAdapter
from etl_migration_core.targets.registry import TargetPlatformRegistry
from etl_target_fabric.capacity.model import (
    build_alteryx_ir_capacity_profile,
    build_capacity_profile,
)
from etl_target_fabric.compilers.expr_ast import (
    ExpressionParseError,
    parse_expression,
    translate_expression_ast,
)
from etl_target_fabric.provider import FabricTargetProvider

SAMPLES = Path(__file__).parents[1] / "alteryx-workflows"


def test_alteryx_adapter_emits_structured_parsed_config_in_ir() -> None:
    sample = SAMPLES / "02_low_west_sample.yxmd"
    adapter = AlteryxSourceAdapter()
    match = adapter.probe(sample, sample.name)
    assert match is not None
    package = adapter.parse(sample, match)

    assert package.source_platform is SourcePlatform.ALTERYX
    nodes = package.assets[0].mapping_graphs[0].nodes
    parsed_nodes = [
        node for node in nodes if isinstance(node.properties.get("parsed_config"), dict)
    ]
    assert parsed_nodes


def test_alteryx_ir_capacity_profile_matches_legacy_graph_profile() -> None:
    sample = SAMPLES / "02_low_west_sample.yxmd"
    adapter = AlteryxSourceAdapter()
    match = adapter.probe(sample, sample.name)
    assert match is not None
    package, graph = adapter.parse_with_graph(sample, match)

    legacy = build_capacity_profile(sample, graph=graph)
    from_ir = build_alteryx_ir_capacity_profile(package.assets[0])
    assert from_ir == legacy

    capacity = FabricTargetProvider().capacity_estimator().estimate_package_capacity(package)
    assert capacity.platform_id == "fabric"
    assert capacity.asset_count == 1
    assert capacity.modeled_count == 1


def test_expression_ast_translates_deterministically_and_fails_closed() -> None:
    m_expr = translate_expression_ast(
        'IIF(IsNull([Amount]), 0, ToNumber([Amount]) * 2)', "dataflow"
    )
    spark_expr = translate_expression_ast(
        'IIF(IsNull([Amount]), 0, ToNumber([Amount]) * 2)', "notebook"
    )
    assert m_expr == (
        '(if (Record.Field(_, "Amount") = null) then 0 '
        'else (Number.From(Record.Field(_, "Amount")) * 2))'
    )
    assert spark_expr == (
        'F.when((F.col("Amount")).isNull(), F.lit(0))'
        ".otherwise((((F.col(\"Amount\")).cast('double')) * (F.lit(2))))"
    )

    assert translate_expression_ast('Uppercase([Region]) + "-" + [Code]', "dataflow") is not None
    assert translate_expression_ast('COALESCE([A], [B], "default")', "notebook") == (
        'F.coalesce(F.col("A"), F.col("B"), F.lit("default"))'
    )

    # Unsupported function and excessive nesting fail closed.
    assert translate_expression_ast("EvalDangerous([X])", "dataflow") is None
    with pytest.raises(ExpressionParseError, match="nesting"):
        parse_expression("(" * 40 + "1" + ")" * 40)


def test_target_spi_dry_run_validation_and_deployment_gates() -> None:
    registry = TargetPlatformRegistry((FabricTargetProvider(),))
    artifact = TargetArtifact(
        workflow="orders.yxmd",
        target_kind="dataflow",
        validation_state="generated_unvalidated",
        deployable=True,
        metadata={"runtime_ready": False},
    )

    allowed = registry.plan_dry_run(
        "fabric",
        [artifact],
        approved_destination="ws-dev",
        requested_destination="ws-dev",
    )
    assert allowed.allowed is True
    assert allowed.planned_mutations == ("Create dataflow item for orders.yxmd",)

    blocked = registry.plan_dry_run(
        "fabric",
        [artifact],
        approved_destination="ws-dev",
        requested_destination="ws-prod",
    )
    assert blocked.allowed is False
    assert blocked.blockers

    with pytest.raises(UnsupportedTargetCapabilityError):
        registry.validate_artifacts("fabric", [artifact])
    with pytest.raises(UnsupportedTargetCapabilityError):
        registry.build_deployment_spec(
            "fabric",
            target_kind="dataflow",
            destination="ws-dev",
            artifact_path="orders",
        )

    assert TargetValidationResult(platform_id="x", provider_version="1.0.0", valid=True).valid
    spec = TargetDeploymentSpec(
        platform_id="x",
        provider_version="1.0.0",
        target_kind="notebook",
        artifact_path="orders",
        inputs={"workspace": "ws-dev"},
    )
    assert spec.inputs["workspace"] == "ws-dev"


def test_run_store_protocol_and_paginated_runs_api(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    store = RunStore(tmp_path / "state")
    try:
        assert isinstance(store, RunStoreProtocol)
    finally:
        store.close()

    monkeypatch.setenv("ACCELERATOR_STATE_DIR", str(tmp_path / "api-state"))
    with RunService(tmp_path / "api-state") as service:
        snap = service.preview(SAMPLES / "02_low_west_sample.yxmd").snapshot_id
        first = service.create_run(snap)
        second = service.create_run(snap)
        runs, total = service.list_runs(limit=1, offset=0)
        assert total == 2
        assert len(runs) == 1
        assert runs[0].id in {first.id, second.id}

    client = TestClient(app, base_url="http://localhost")
    app.state.run_service = RunService(tmp_path / "api-state")
    try:
        resp = client.get("/api/runs", params={"limit": 1, "offset": 0})
        assert resp.status_code == 200
        body = resp.json()
        assert body["total"] == 2
        assert body["limit"] == 1
        assert len(body["runs"]) == 1
    finally:
        app.state.run_service.close()
