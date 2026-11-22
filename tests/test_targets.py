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
from etl_migration_core.host import PluginHost
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
    assert catalog.status_code == 200
    assert catalog.json()["targets"] == []
    assert catalog.json()["faults"][0]["platform_id"] == "example"
    assert "inconsistent metadata" in catalog.json()["faults"][0]["detail"]


def test_one_faulty_target_provider_does_not_hide_healthy_targets(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    class BrokenProvider:
        platform_id = "broken"
        display_name = "Broken"
        provider_version = "1.0.0"
        supported_ir_versions = ("1.0.0",)
        implemented = True
        capabilities: tuple[TargetCapability, ...] = ("evaluate",)
        description = "Raises while describing itself"

        def info(self) -> TargetPlatformInfo:
            raise RuntimeError("provider exploded")

        def evaluator(self) -> TargetEvaluator | None:
            raise RuntimeError("provider exploded")

    registry = create_default_target_registry(load_entry_points=False)
    registry.register(BrokenProvider())
    monkeypatch.setattr(app.state, "target_registry", registry, raising=False)
    client = TestClient(app, base_url="http://127.0.0.1")

    payload = client.get("/api/targets").json()
    assert {item["platform_id"] for item in payload["targets"]} == {
        "databricks",
        "fabric",
        "snowflake",
        "synapse",
    }
    assert payload["faults"] == [
        {
            "platform_id": "broken",
            "detail": "TargetProviderFaultError: Target provider 'broken' faulted during "
            "describe: RuntimeError: provider exploded",
        }
    ]
    assert client.get("/api/targets/broken").status_code == 409
    package = _sample_package()
    with pytest.raises(ValueError, match="faulted during describe"):
        registry.evaluate_asset("broken", package, package.assets[0], base_reason="test")


def test_target_registry_records_broken_entry_points_when_isolating(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    class EntryPoint:
        def __init__(self, name: str, loader: object) -> None:
            self.name = name
            self._loader = loader

        def load(self) -> object:
            if isinstance(self._loader, Exception):
                raise self._loader
            return self._loader

    healthy = create_default_target_registry(load_entry_points=False).get("fabric")
    monkeypatch.setattr(
        "etl_migration_core.targets.registry.entry_points",
        lambda **_kwargs: [
            EntryPoint("broken", ImportError("No module named 'missing_plugin'")),
            EntryPoint("hidden", healthy),
            EntryPoint("healthy", healthy),
        ],
    )

    registry = TargetPlatformRegistry(builtin_placeholder_providers())
    with pytest.raises(ImportError, match="missing_plugin"):
        registry.load_entry_points()

    registry = TargetPlatformRegistry(builtin_placeholder_providers())
    assert registry.load_entry_points(allowlist={"broken", "healthy"}, on_error="record") == 1
    outcomes = {item.name: item for item in registry.plugin_results}
    assert outcomes["broken"].status == "failed"
    assert "ImportError: No module named 'missing_plugin'" in (outcomes["broken"].detail or "")
    assert outcomes["hidden"].status == "skipped"
    assert outcomes["healthy"].status == "loaded"
    assert outcomes["healthy"].provides == "fabric"
    assert registry.origin_of("fabric") == "plugin:healthy"
    assert registry.origin_of("databricks") == "builtin"


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


def test_target_kinds_are_advertised_and_validated_against_the_code_generator() -> None:
    registry = create_default_target_registry(load_entry_points=False)
    assert registry.get_info("fabric").target_kinds == ("dataflow", "notebook", "pipeline")
    assert registry.get_info("databricks").target_kinds == ()

    class GeneratorWithoutKinds:
        platform_id = "kinds"
        display_name = "Kinds"
        provider_version = "1.0.0"
        supported_ir_versions = ("1.0.0",)
        implemented = True
        capabilities: tuple[TargetCapability, ...] = ("codegen",)
        description = "Advertises codegen but forgets to publish its target kinds"

        def info(self) -> TargetPlatformInfo:
            return TargetPlatformInfo(
                platform_id=self.platform_id,
                display_name=self.display_name,
                provider_version=self.provider_version,
                implemented=True,
                status="ready",
                capabilities=self.capabilities,
            )

        def evaluator(self) -> TargetEvaluator | None:
            return None

        def code_generator(self) -> object:
            return registry.get("fabric").code_generator()  # type: ignore[attr-defined]

    registry.register(GeneratorWithoutKinds())

    catalog = registry.catalog()
    assert [fault.platform_id for fault in catalog.faults] == ["kinds"]
    assert "inconsistent metadata" in catalog.faults[0].detail
    assert {info.platform_id for info in catalog.targets} == {
        "databricks",
        "fabric",
        "snowflake",
        "synapse",
    }


def test_plugin_host_reports_invalid_providers_as_structured_diagnostics() -> None:
    class BrokenProvider:
        platform_id = "broken"
        display_name = "Broken"
        provider_version = "1.0.0"
        supported_ir_versions = ("1.0.0",)
        implemented = True
        capabilities: tuple[TargetCapability, ...] = ("evaluate",)
        description = "Raises while describing itself"

        def info(self) -> TargetPlatformInfo:
            raise RuntimeError("provider exploded")

        def evaluator(self) -> TargetEvaluator | None:
            return None

    registry = create_default_target_registry(load_entry_points=False)
    registry.register(BrokenProvider())

    catalog = PluginHost(None, registry).catalog()

    assert [(item.code, item.severity, item.stage) for item in catalog.diagnostics] == [
        ("TARGET_PROVIDER_INVALID", "error", "plugin")
    ]
    assert "broken: TargetProviderFaultError" in catalog.diagnostics[0].message
    assert {item.platform_id for item in catalog.targets} == {
        "databricks",
        "fabric",
        "snowflake",
        "synapse",
    }
    assert {item.origin for item in catalog.targets} == {"builtin"}
    assert catalog.failed_count == 0


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


def test_sources_status_and_provider_capability_apis(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    source = Path(__file__).parent / "fixtures" / "powercenter" / "basic_repository.xml"
    with RunService(tmp_path / "state") as service:
        preview = service.preview(source)
        run = service.create_run(preview.snapshot_id)
        service.execute(run.id)
        monkeypatch.setattr(app.state, "run_service", service, raising=False)
        client = TestClient(app, base_url="http://127.0.0.1")

        sources_resp = client.get("/api/sources")
        assert sources_resp.status_code == 200
        source_ids = {item["adapter_id"] for item in sources_resp.json()["sources"]}
        assert {"alteryx", "informatica-idmc", "informatica-powercenter"} <= source_ids

        status_resp = client.get(f"/api/runs/{run.id}/status")
        assert status_resp.status_code == 200
        assert status_resp.json()["status"] == "completed"
        assert "result" not in status_resp.json()

        slim_run = client.get(f"/api/runs/{run.id}?include_result=false")
        assert slim_run.status_code == 200
        assert slim_run.json()["result"] is None

        gen_resp = client.post(
            f"/api/runs/{run.id}/targets/fabric/generate?target_kind=notebook"
        )
        assert gen_resp.status_code == 200
        assert gen_resp.json()[0]["platform_id"] == "fabric"
        assert gen_resp.json()[0]["artifacts"]

        cap_resp = client.get(f"/api/runs/{run.id}/targets/fabric/capacity")
        assert cap_resp.status_code == 200
        assert cap_resp.json()[0]["platform_id"] == "fabric"

        assert (
            client.post(
                f"/api/runs/{run.id}/targets/snowflake/generate?target_kind=notebook"
            ).status_code
            == 409
        )
        assert client.get(f"/api/runs/{run.id}/targets/snowflake/capacity").status_code == 409
