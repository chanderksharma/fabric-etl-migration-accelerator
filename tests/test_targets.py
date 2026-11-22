"""Tests for pluggable target platform SPI, placeholders, and neutral assessment."""

from __future__ import annotations

import json
from importlib.util import module_from_spec, spec_from_file_location
from pathlib import Path

import pytest
from fastapi.testclient import TestClient
from typer.testing import CliRunner

from accelerator.cli.app import app as cli_app
from accelerator.runtime.runs import RunService
from accelerator.server.api import app
from accelerator.targets import (
    TargetPlatformRegistry,
    UnknownTargetPlatformError,
    builtin_placeholder_providers,
    create_default_target_registry,
)
from etl_migration_core.contracts.ir import (
    EXTENSIBLE_SOURCE_IR_VERSION,
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
    TargetEvaluation,
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


def test_target_registry_rejects_misleading_capability_metadata(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    provider = create_default_target_registry(load_entry_points=False).get("fabric")

    class MisleadingProvider:
        platform_id = "example"
        display_name = "Example"
        provider_version = "1.0.0"
        supported_ir_versions = ("1.0.0",)
        implemented = True
        capabilities: tuple[TargetCapability, ...] = ("evaluate",)
        description = "Synthetic"

        def evaluator(self) -> TargetEvaluator | None:
            return provider.evaluator()

        def info(self) -> TargetPlatformInfo:
            return TargetPlatformInfo(
                platform_id=self.platform_id,
                display_name=self.display_name,
                provider_version=self.provider_version,
                supported_ir_versions=self.supported_ir_versions,
                implemented=True,
                status="ready",
                capabilities=("evaluate", "codegen"),
            )

    registry = TargetPlatformRegistry([MisleadingProvider()])
    with pytest.raises(ValueError, match="inconsistent metadata"):
        registry.list_providers()
    with pytest.raises(ValueError, match="inconsistent metadata"):
        registry.require_implemented("example", capability="evaluate")
    package = _sample_package()
    with pytest.raises(ValueError, match="inconsistent metadata"):
        registry.evaluate_asset("example", package, package.assets[0], base_reason="test")
    monkeypatch.setattr(app.state, "target_registry", registry, raising=False)
    client = TestClient(app, base_url="http://127.0.0.1")
    response = client.get("/api/targets/example")
    assert response.status_code == 409
    assert "inconsistent metadata" in response.json()["detail"]
    catalog = client.get("/api/targets")
    assert catalog.status_code == 409
    assert "inconsistent metadata" in catalog.json()["detail"]


def test_target_registry_reports_duplicate_entry_points(monkeypatch: pytest.MonkeyPatch) -> None:
    provider = create_default_target_registry(load_entry_points=False).get("fabric")

    class EntryPoint:
        def __init__(self, name: str) -> None:
            self.name = name

        def load(self) -> object:
            return provider

    monkeypatch.setattr(
        "etl_migration_core.targets.registry.entry_points",
        lambda **_kwargs: [EntryPoint("first"), EntryPoint("second")],
    )
    registry = TargetPlatformRegistry([provider])
    with pytest.raises(ValueError, match="duplicate target platform entry point"):
        registry.load_entry_points()


def test_packaged_example_is_manual_review_only() -> None:
    source = (
        Path(__file__).parents[1]
        / "examples"
        / "plugins"
        / "synthetic-databricks"
        / "src"
        / "etl_target_databricks_example"
        / "__init__.py"
    )
    spec = spec_from_file_location("synthetic_target_example", source)
    assert spec is not None and spec.loader is not None
    module = module_from_spec(spec)
    spec.loader.exec_module(module)
    registry = TargetPlatformRegistry(builtin_placeholder_providers())
    registry.register(module.SyntheticDatabricksProvider(), replace_placeholder=True)

    package = _sample_package()
    result = registry.evaluate_asset("databricks", package, package.assets[0], base_reason="test")
    assert result.recommended_target == "Manual review"
    assert result.target_components == ()
    assert "Synthetic example only" in result.diagnostics[0]
    with pytest.raises(UnsupportedTargetCapabilityError):
        registry.require_implemented("databricks", capability="codegen")


def test_registry_evaluates_partial_plugin_and_checks_compatibility() -> None:
    class Evaluator:
        def evaluate_asset(
            self, package: EtlPackage, asset: EtlAsset, *, base_reason: str
        ) -> TargetEvaluation:
            return TargetEvaluation(
                platform_id="databricks",
                recommended_target="Manual review",
                recommendation_reason=base_reason,
            )

    class Provider:
        platform_id = "databricks"
        display_name = "Databricks"
        provider_version = "0.1.0"
        supported_ir_versions = ("1.0.0",)
        implemented = True
        capabilities: tuple[TargetCapability, ...] = ("evaluate",)
        description = "Synthetic evaluate-only provider"

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

        def evaluator(self) -> Evaluator:
            return Evaluator()

    registry = TargetPlatformRegistry([Provider()])
    package = _sample_package()
    result = registry.evaluate_asset("databricks", package, package.assets[0], base_reason="test")
    assert result.platform_id == "databricks"
    with pytest.raises(UnsupportedTargetCapabilityError):
        registry.require_implemented("databricks", capability="codegen")
    future = package.model_copy(update={"ir_version": "99.0.0"})
    with pytest.raises(ValueError, match="does not support IR version"):
        registry.evaluate_asset("databricks", future, future.assets[0], base_reason="test")
    other_asset = package.assets[0].model_copy(update={"native_id": "other"})
    with pytest.raises(ValueError, match="does not belong"):
        registry.evaluate_asset("databricks", package, other_asset, base_reason="test")
    external_data = package.model_dump()
    external_data["source_platform"] = "ssis"
    external_data["ir_version"] = EXTENSIBLE_SOURCE_IR_VERSION
    external = EtlPackage.model_validate(external_data)
    with pytest.raises(ValueError, match="does not support IR version"):
        registry.evaluate_asset("databricks", external, external.assets[0], base_reason="test")

    class ExtensibleProvider(Provider):
        supported_ir_versions = (EXTENSIBLE_SOURCE_IR_VERSION,)

    extensible = TargetPlatformRegistry([ExtensibleProvider()])
    assert extensible.evaluate_asset(
        "databricks", external, external.assets[0], base_reason="test"
    ).platform_id == "databricks"


def test_registry_rejects_missing_advertised_evaluator() -> None:
    class MissingEvaluator:
        platform_id = "example"
        display_name = "Example"
        provider_version = "0.1.0"
        supported_ir_versions = ("1.0.0",)
        implemented = True
        capabilities: tuple[TargetCapability, ...] = ("evaluate",)
        description = "Synthetic provider"

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

        def evaluator(self) -> None:
            return None

    package = _sample_package()
    registry = TargetPlatformRegistry([MissingEvaluator()])
    with pytest.raises(UnsupportedTargetCapabilityError, match="does not provide an evaluator"):
        registry.evaluate_asset("example", package, package.assets[0], base_reason="test")


def test_target_evaluation_api_uses_registered_provider(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    class Evaluator:
        def evaluate_asset(
            self, package: EtlPackage, asset: EtlAsset, *, base_reason: str
        ) -> TargetEvaluation:
            return TargetEvaluation(
                platform_id="databricks",
                recommended_target="Manual review",
                recommendation_reason=base_reason,
            )

    class Provider:
        platform_id = "databricks"
        display_name = "Databricks"
        provider_version = "0.1.0"
        supported_ir_versions = ("1.0.0",)
        implemented = True
        capabilities: tuple[TargetCapability, ...] = ("evaluate",)
        description = "Synthetic evaluate-only provider"

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

        def evaluator(self) -> Evaluator:
            return Evaluator()

    source = Path(__file__).parent / "fixtures" / "idmc" / "basic_export"
    registry = TargetPlatformRegistry(builtin_placeholder_providers())
    registry.register(Provider(), replace_placeholder=True)
    with RunService(tmp_path / "state") as service:
        run = service.create_run(service.preview(source).snapshot_id)
        service.execute(run.id)
        before = service.get_run(run.id).result
        monkeypatch.setattr(app.state, "run_service", service, raising=False)
        monkeypatch.setattr(app.state, "target_registry", registry, raising=False)
        client = TestClient(app, base_url="http://127.0.0.1")

        automatic = client.get(f"/api/runs/{run.id}/neutral-assessment")
        assert automatic.status_code == 200
        neutral = client.post(f"/api/runs/{run.id}/neutral-assessment")
        assert neutral.status_code == 200
        assert automatic.json() == neutral.json()
        expected = PortfolioAssessmentApplication().assess_neutral(source)
        assert neutral.json()["assessments"] == [
            item.model_dump(mode="json") for item in expected.assessments
        ]
        assert client.get(f"/api/runs/{run.id}/neutral-assessment").json() == neutral.json()

        response = client.post(f"/api/runs/{run.id}/targets/databricks/evaluate")
        assert response.status_code == 200
        evaluations = response.json()
        assert len(evaluations) == 3
        assert all(item["provider_version"] == "0.1.0" for item in evaluations)
        assert all(item["evaluation"]["platform_id"] == "databricks" for item in evaluations)
        assert all(
            item["evaluation"]["recommended_target"] == "Manual review" for item in evaluations
        )
        saved = client.get(f"/api/runs/{run.id}/targets/DATABRICKS/evaluate")
        assert saved.status_code == 200
        assert saved.json() == evaluations
        assert service.get_run(run.id).result == before
        assert client.post(f"/api/runs/{run.id}/targets/snowflake/evaluate").status_code == 409
        assert client.post(f"/api/runs/{run.id}/targets/missing/evaluate").status_code == 404
        assert client.get(f"/api/runs/{run.id}/targets/snowflake/evaluate").status_code == 404

    with RunService(tmp_path / "state") as reopened:
        assert len(reopened.get_target_evaluations(run.id, "databricks")) == 3
        assert len(reopened.get_neutral_assessment(run.id).assessments) == 3


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
