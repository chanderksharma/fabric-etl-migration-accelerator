"""Tests for pluggable target platform SPI, placeholders, and neutral assessment."""

from __future__ import annotations

import json
from pathlib import Path

import pytest
from fastapi.testclient import TestClient
from typer.testing import CliRunner

from accelerator.cli.app import app as cli_app
from accelerator.server.api import app
from accelerator.targets import (
    TargetPlatformRegistry,
    UnknownTargetPlatformError,
    builtin_placeholder_providers,
    create_default_target_registry,
)
from etl_migration_core.contracts.ir import (
    AssetType,
    EtlAsset,
    EtlEdge,
    EtlGraph,
    EtlNode,
    EtlPackage,
    GraphKind,
    NodeKind,
    SourcePlatform,
)
from etl_migration_core.contracts.spi import (
    TargetCapability,
    TargetEvaluator,
    TargetPlatformInfo,
    UnsupportedTargetCapabilityError,
)
from etl_portfolio_assessment.assessment.engine import assess_package_neutral
from etl_portfolio_assessment.assessment.workload_profile import extract_workload_profile
from etl_portfolio_assessment.service.application import PortfolioAssessmentApplication


def _sample_package() -> EtlPackage:
    mapping = EtlGraph(
        kind=GraphKind.MAPPING,
        nodes=(
            EtlNode(
                native_id="1",
                name="OrdersInput",
                operation="source",
                kind=NodeKind.SOURCE,
            ),
            EtlNode(
                native_id="2",
                name="FilterActive",
                operation="filter",
                kind=NodeKind.TRANSFORMATION,
            ),
            EtlNode(
                native_id="3",
                name="PythonScore",
                operation="python",
                kind=NodeKind.TRANSFORMATION,
            ),
            EtlNode(
                native_id="4",
                name="OrdersOut",
                operation="target",
                kind=NodeKind.TARGET,
            ),
        ),
        edges=(
            EtlEdge(source="1", target="2"),
            EtlEdge(source="2", target="3"),
            EtlEdge(source="3", target="4"),
        ),
    )
    asset = EtlAsset(
        native_id="m_orders",
        name="m_orders",
        asset_type=AssetType.MAPPING,
        mapping_graphs=(mapping,),
    )
    return EtlPackage(
        source_platform=SourcePlatform.INFORMATICA_POWERCENTER,
        source_product="Informatica PowerCenter",
        export_id="orders.xml",
        assets=(asset,),
    )


def test_default_target_registry_lists_fabric_and_placeholders() -> None:
    registry = create_default_target_registry(load_entry_points=False)
    providers = {info.platform_id: info for info in registry.list_providers()}

    assert set(providers) == {"databricks", "fabric", "snowflake", "synapse"}
    assert providers["fabric"].implemented is True
    assert providers["fabric"].status == "ready"
    assert "codegen" in providers["fabric"].capabilities

    for placeholder_id in ("databricks", "synapse", "snowflake"):
        info = providers[placeholder_id]
        assert info.implemented is False
        assert info.status == "placeholder"
        assert info.capabilities == ()
        with pytest.raises(UnsupportedTargetCapabilityError):
            registry.require_implemented(placeholder_id, capability="codegen")

    with pytest.raises(UnknownTargetPlatformError):
        registry.get("nonexistent")


def test_external_target_plugin_replaces_builtin_placeholder() -> None:
    class MockDatabricksProvider:
        platform_id = "databricks"
        display_name = "Azure Databricks"
        provider_version = "0.1.0"
        supported_ir_versions = ("1.0.0",)
        implemented = True
        capabilities: tuple[TargetCapability, ...] = ("evaluate",)
        description = "Test plugin"

        def info(self) -> TargetPlatformInfo:
            return TargetPlatformInfo(
                platform_id=self.platform_id,
                display_name=self.display_name,
                provider_version=self.provider_version,
                supported_ir_versions=self.supported_ir_versions,
                implemented=True,
                status="ready",
                capabilities=self.capabilities,
                description=self.description,
            )

        def evaluator(self) -> TargetEvaluator | None:
            return None

    registry = TargetPlatformRegistry(builtin_placeholder_providers())
    registry.register(MockDatabricksProvider(), replace_placeholder=True)
    resolved = registry.require_implemented("databricks", capability="evaluate")
    assert resolved.provider_version == "0.1.0"


def test_placeholder_provider_fails_closed() -> None:
    placeholders = {p.platform_id: p for p in builtin_placeholder_providers()}
    assert placeholders["snowflake"].evaluator() is None
    with pytest.raises(UnsupportedTargetCapabilityError, match="roadmap placeholder"):
        placeholders["snowflake"].require_capability("codegen")


def test_target_catalog_api_and_cli() -> None:
    client = TestClient(app, base_url="http://127.0.0.1")
    resp = client.get("/api/targets")
    assert resp.status_code == 200
    items = {item["platform_id"]: item for item in resp.json()["targets"]}
    assert items["fabric"]["implemented"] is True
    assert items["databricks"]["implemented"] is False
    assert items["synapse"]["implemented"] is False
    assert items["snowflake"]["implemented"] is False

    one = client.get("/api/targets/snowflake")
    assert one.status_code == 200
    assert one.json()["status"] == "placeholder"

    missing = client.get("/api/targets/unknown-target")
    assert missing.status_code == 404

    cli_result = CliRunner().invoke(cli_app, ["targets"])
    assert cli_result.exit_code == 0
    parsed = json.loads(cli_result.stdout)
    assert len(parsed["targets"]) == 4


def test_neutral_assessment_and_workload_profile_contain_no_fabric_terms(
    tmp_path: Path,
) -> None:
    package = _sample_package()
    assessments = assess_package_neutral(package)
    assert len(assessments) == 1
    assessment = assessments[0]
    assert assessment.wave_tier in {"Wave 1", "Wave 2", "Wave 3", "Wave 4"}
    serialized = repr(assessment).casefold()
    assert "dataflow" not in serialized
    assert "f-sku" not in serialized

    profile = extract_workload_profile(package, package.assets[0])
    assert profile.total_steps == 4
    assert profile.script_steps == 1
    assert profile.counts["sources"] == 1
    assert profile.counts["targets"] == 1

    sample_dir = Path(__file__).parents[1] / "alteryx-workflows"
    neutral_estate = PortfolioAssessmentApplication().assess_neutral(sample_dir)
    assert neutral_estate.failed_count == 0
    assert neutral_estate.workflow_count > 0
