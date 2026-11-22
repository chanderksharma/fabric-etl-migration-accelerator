"""Source adapter registration and dispatch contracts."""

import io
import json
import time
from dataclasses import dataclass, replace
from importlib import import_module
from importlib.util import module_from_spec, spec_from_file_location
from pathlib import Path
from unittest.mock import mock_open
from zipfile import ZipFile

import pytest
from fastapi.testclient import TestClient
from typer.testing import CliRunner

from accelerator.runtime.runs import RunService, _snapshot_id
from accelerator.server.api import app
from etl_migration_core.contracts.ir import (
    EXTENSIBLE_SOURCE_IR_VERSION,
    IR_VERSION,
    EtlPackage,
    SourcePlatform,
)
from etl_migration_core.intake.discovery import DiscoveryService
from etl_migration_core.intake.domain import DiscoveryLimits, SkipReason
from etl_migration_core.sources.base import SourceMatch
from etl_migration_core.sources.defaults import create_default_registry
from etl_migration_core.sources.registry import (
    AmbiguousSourceFormatError,
    SourceAdapterRegistry,
    UnknownSourceFormatError,
)
from etl_migration_core.targets.registry import TargetPlatformRegistry
from etl_portfolio_assessment.assessment.engine import assess_package_neutral
from etl_portfolio_assessment.assessment.workload_profile import extract_workload_profile
from etl_portfolio_assessment.service.application import PortfolioAssessmentApplication


@dataclass(frozen=True)
class FakeAdapter:
    adapter_id: str
    platform: SourcePlatform | str
    product: str
    confidence: int
    marker: bytes
    adapter_version: str = "1.0"
    parser_version: str = "1.0"
    registry_version: str = "1.0"
    rules_version: str = "1.0"

    def probe(self, path: Path, display_path: str) -> SourceMatch | None:
        if self.marker not in path.read_bytes():
            return None
        return SourceMatch(
            adapter_id=self.adapter_id,
            platform=self.platform,
            product=self.product,
            asset_type="workflow",
            confidence=self.confidence,
            display_path=display_path,
        )

    def parse(self, path: Path, match: SourceMatch) -> EtlPackage:
        return EtlPackage(
            ir_version=(
                IR_VERSION
                if isinstance(self.platform, SourcePlatform)
                else EXTENSIBLE_SOURCE_IR_VERSION
            ),
            source_platform=self.platform,
            source_product=self.product,
            export_id=match.display_path,
        )


def _with_version(adapter: FakeAdapter, field: str, value: str) -> FakeAdapter:
    return replace(
        adapter,
        adapter_version=value if field == "adapter_version" else adapter.adapter_version,
        parser_version=value if field == "parser_version" else adapter.parser_version,
        registry_version=value if field == "registry_version" else adapter.registry_version,
        rules_version=value if field == "rules_version" else adapter.rules_version,
    )


def test_registry_selects_highest_confidence_adapter(tmp_path: Path) -> None:
    source = tmp_path / "workflow.xml"
    source.write_bytes(b"POWERMART")
    registry = SourceAdapterRegistry(
        (
            FakeAdapter(
                "generic-xml",
                SourcePlatform.ALTERYX,
                "Generic XML",
                20,
                b"POWER",
            ),
            FakeAdapter(
                "powercenter",
                SourcePlatform.INFORMATICA_POWERCENTER,
                "PowerCenter",
                100,
                b"POWERMART",
            ),
        )
    )

    detected = registry.detect(source, "workflow.xml")

    assert detected.match.adapter_id == "powercenter"
    assert detected.adapter.platform is SourcePlatform.INFORMATICA_POWERCENTER
    assert registry.parse(source, detected.match).source_product == "PowerCenter"


def test_registry_rejects_unknown_and_ambiguous_formats(tmp_path: Path) -> None:
    source = tmp_path / "workflow.bin"
    source.write_bytes(b"same")
    unknown = SourceAdapterRegistry(
        (
            FakeAdapter(
                "powercenter",
                SourcePlatform.INFORMATICA_POWERCENTER,
                "PowerCenter",
                100,
                b"POWERMART",
            ),
        )
    )
    with pytest.raises(UnknownSourceFormatError, match=r"workflow\.bin"):
        unknown.detect(source, "workflow.bin")

    ambiguous = SourceAdapterRegistry(
        (
            FakeAdapter(
                "first",
                SourcePlatform.INFORMATICA_POWERCENTER,
                "PowerCenter",
                100,
                b"same",
            ),
            FakeAdapter(
                "second",
                SourcePlatform.INFORMATICA_IDMC,
                "IDMC",
                100,
                b"same",
            ),
        )
    )
    with pytest.raises(AmbiguousSourceFormatError, match=r"first, second"):
        ambiguous.detect(source, "workflow.bin")


def test_registry_rejects_duplicate_adapter_ids() -> None:
    adapter = FakeAdapter(
        "duplicate",
        SourcePlatform.ALTERYX,
        "Alteryx",
        100,
        b"AlteryxDocument",
    )

    with pytest.raises(ValueError, match="duplicate source adapter"):
        SourceAdapterRegistry((adapter, adapter))


def test_default_registry_contains_all_source_platforms() -> None:
    registry = create_default_registry()

    assert {
        adapter.platform for adapter in registry.adapters
    } == set(SourcePlatform)


@pytest.mark.parametrize(
    ("name", "content", "adapter_id"),
    [
        ("source.yxmd", b"<AlteryxDocument/>", "alteryx"),
        ("source.xml", b"<POWERMART/>", "informatica-powercenter"),
    ],
)
def test_builtin_file_probes_do_not_read_entire_files(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    name: str,
    content: bytes,
    adapter_id: str,
) -> None:
    source = tmp_path / name
    source.write_bytes(content)
    adapter = next(
        item
        for item in create_default_registry(load_entry_points=False).adapters
        if item.adapter_id == adapter_id
    )

    opened = mock_open(read_data=content)
    monkeypatch.setattr(Path, "open", opened)
    assert adapter.probe(source, name) is not None
    opened.return_value.read.assert_called_once_with(64_000)


def test_external_source_identifier_survives_detection_and_ir_round_trip(tmp_path: Path) -> None:
    source = tmp_path / "synthetic.dtsx"
    source.write_bytes(b"synthetic ssis marker")
    registry = SourceAdapterRegistry(
        (FakeAdapter("synthetic-ssis", "ssis", "Synthetic SSIS", 100, b"ssis"),)
    )

    detected = registry.detect(source, source.name)
    package = registry.parse(source, detected.match)
    assert package.source_platform == "ssis"
    assert EtlPackage.model_validate_json(package.model_dump_json()).source_platform == "ssis"


@pytest.mark.parametrize("version", ["1.0.0", "0.9.9", "invalid"])
def test_external_source_requires_extensible_ir_version(version: str) -> None:
    with pytest.raises(ValueError, match=r"require IR version 1\.1\.0 or later"):
        EtlPackage(
            ir_version=version, source_platform="ssis", source_product="Synthetic", export_id="test"
        )


@pytest.mark.parametrize("platform", ["SSIS", "../ssis", "", "a" * 65])
def test_source_platform_rejects_invalid_identifiers(platform: str) -> None:
    with pytest.raises(ValueError, match="lowercase identifier"):
        EtlPackage(source_platform=platform, source_product="Synthetic", export_id="test")


def test_known_source_identifier_round_trip_preserves_enum() -> None:
    package = EtlPackage(
        source_platform=SourcePlatform.ALTERYX,
        source_product="Synthetic",
        export_id="test",
    )
    restored = EtlPackage.model_validate_json(package.model_dump_json())
    assert restored.source_platform is SourcePlatform.ALTERYX


def test_registry_rejects_inconsistent_plugin_metadata(tmp_path: Path) -> None:
    source = tmp_path / "synthetic.dtsx"
    source.write_bytes(b"ssis")

    class WrongMatchAdapter(FakeAdapter):
        def probe(self, path: Path, display_path: str) -> SourceMatch | None:
            match = super().probe(path, display_path)
            return match.model_copy(update={"adapter_id": "other"}) if match else None

    class WrongPackageAdapter(FakeAdapter):
        def parse(self, path: Path, match: SourceMatch) -> EtlPackage:
            return EtlPackage(
                ir_version=EXTENSIBLE_SOURCE_IR_VERSION,
                source_platform="other",
                source_product="other",
                export_id="test",
            )

    bad_match = WrongMatchAdapter("ssis", "ssis", "SSIS", 100, b"ssis")
    with pytest.raises(ValueError, match="inconsistent identity"):
        SourceAdapterRegistry((bad_match,)).detect(source, source.name)

    bad_package = WrongPackageAdapter("ssis", "ssis", "SSIS", 100, b"ssis")
    registry = SourceAdapterRegistry((bad_package,))
    detected = registry.detect(source, source.name)
    with pytest.raises(ValueError, match="different platform"):
        registry.parse(source, detected.match)


def test_registry_reports_duplicate_entry_point(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    adapter = FakeAdapter("ssis", "ssis", "SSIS", 100, b"ssis")

    class EntryPoint:
        name = "duplicate"

        def load(self) -> FakeAdapter:
            return adapter

    monkeypatch.setattr(
        "etl_migration_core.sources.registry.entry_points",
        lambda **_kwargs: [EntryPoint()],
    )
    registry = SourceAdapterRegistry((adapter,))
    with pytest.raises(ValueError, match="duplicate source adapter identity"):
        registry.load_entry_points()


def _synthetic_ssis_registry() -> SourceAdapterRegistry:
    source = (
        Path(__file__).parents[1]
        / "examples"
        / "plugins"
        / "synthetic-ssis"
        / "src"
        / "etl_source_ssis_example"
        / "__init__.py"
    )
    spec = spec_from_file_location("synthetic_ssis_example", source)
    assert spec is not None and spec.loader is not None
    module = module_from_spec(spec)
    spec.loader.exec_module(module)
    return SourceAdapterRegistry((module.SyntheticSsisAdapter(),))


def test_synthetic_ssis_plugin_extracts_manual_only_metadata() -> None:
    source = (
        Path(__file__).parents[1]
        / "examples"
        / "plugins"
        / "synthetic-ssis"
        / "fixtures"
        / "synthetic-package.dtsx"
    )
    registry = _synthetic_ssis_registry()
    detected = registry.detect(source, source.name)
    package = registry.parse(source, detected.match)
    assert package.ir_version == EXTENSIBLE_SOURCE_IR_VERSION
    assert package.source_platform == "ssis"
    assert package.assets[0].orchestration_graph is not None
    assert len(package.assets[0].orchestration_graph.nodes) == 2
    assessment = assess_package_neutral(package)[0]
    assert assessment.unknown_components == ("ssis_unverified_task",)
    assert assessment.inventory[0].count == 2
    assert extract_workload_profile(package, package.assets[0]).profile_kind == "generic"


def test_synthetic_ssis_plugin_supports_local_neutral_run(tmp_path: Path) -> None:
    root = Path(__file__).parents[1] / "examples" / "plugins"
    source = root / "synthetic-ssis" / "fixtures" / "synthetic-package.dtsx"
    sources = _synthetic_ssis_registry()
    app = PortfolioAssessmentApplication(source_registry=sources)
    assert app.preview(source).workflow_count == 1
    expected = app.assess_neutral(source)
    assert expected.failed_count == 0
    assert expected.assessments[0].unknown_components == ["ssis_unverified_task"]

    provider_path = (
        root / "synthetic-databricks" / "src" / "etl_target_databricks_example" / "__init__.py"
    )
    spec = spec_from_file_location("synthetic_target_for_ssis", provider_path)
    assert spec is not None and spec.loader is not None
    module = module_from_spec(spec)
    spec.loader.exec_module(module)
    targets = TargetPlatformRegistry((module.SyntheticDatabricksProvider(),))

    with RunService(tmp_path / "state", source_registry=sources) as service:
        preview = service.preview(source)
        assert preview.workflow_count == 1
        assert preview.workflows[0].source_platform == "ssis"
        run = service.create_run(preview.snapshot_id)
        service.execute(run.id)
        completed = service.get_run(run.id)
        assert completed.status == "completed" and completed.result is not None
        assert completed.result.failed_count == 1
        assert "Fabric assessment does not support source" in completed.result.failures[0]
        neutral = service.get_neutral_assessment(run.id)
        assert neutral.assessments == expected.assessments
        evaluations = service.evaluate_target(run.id, "databricks", targets)
        assert evaluations[0].evaluation.recommended_target == "Manual review"
        assert service.get_target_evaluations(run.id, "databricks") == evaluations
        with pytest.raises(ValueError, match="Fabric generation does not support source"):
            service.generate(run.id, "dataflow")


@pytest.mark.parametrize("nested", [False, True])
def test_synthetic_ssis_plugin_supports_archive_neutral_run(
    tmp_path: Path, nested: bool
) -> None:
    fixture = (
        Path(__file__).parents[1]
        / "examples"
        / "plugins"
        / "synthetic-ssis"
        / "fixtures"
        / "synthetic-package.dtsx"
    )
    archive_path = tmp_path / "source.zip"
    payload = fixture.read_bytes()
    with ZipFile(archive_path, "w") as archive:
        if nested:
            output = io.BytesIO()
            with ZipFile(output, "w") as inner:
                inner.writestr("package.dtsx", payload)
            archive.writestr("nested.yxzp", output.getvalue())
        else:
            archive.writestr("package.dtsx", payload)
    assert DiscoveryService().discover(archive_path).workflow_count == 0
    sources = _synthetic_ssis_registry()
    app = PortfolioAssessmentApplication(source_registry=sources)
    preview = app.preview(archive_path)
    assert preview.workflow_count == 1
    assert preview.workflows[0].parser_version == sources.adapters[0].parser_version
    assert preview.workflows[0].registry_version == sources.adapters[0].registry_version
    assert preview.workflows[0].rules_version == sources.adapters[0].rules_version
    expected_path = "nested.yxzp!package.dtsx" if nested else "package.dtsx"
    assert preview.workflows[0].display_path == expected_path
    expected = app.assess_neutral(archive_path)
    assert expected.failed_count == 0
    assert expected.assessments[0].unknown_components == ["ssis_unverified_task"]
    with RunService(tmp_path / "state", source_registry=sources) as service:
        run = service.create_run(service.preview(archive_path).snapshot_id)
        service.execute(run.id)
        assert service.get_run(run.id).status == "completed"
        assert service.get_neutral_assessment(run.id).assessments == expected.assessments


def test_plugin_archive_reports_invalid_and_oversized_members(tmp_path: Path) -> None:
    archive_path = tmp_path / "source.zip"
    with ZipFile(archive_path, "w") as archive:
        archive.writestr("invalid.dtsx", "<broken")
        archive.writestr("large.dtsx", "x" * 100)
    summary = DiscoveryService(
        DiscoveryLimits(max_file_bytes=50), source_registry=_synthetic_ssis_registry()
    ).discover(archive_path)
    assert summary.workflow_count == 0
    skipped = {item.path: item for item in summary.skipped}
    assert skipped["invalid.dtsx"].reason == SkipReason.UNSUPPORTED_INPUT
    assert "unsafe synthetic SSIS XML" in skipped["invalid.dtsx"].detail
    assert skipped["large.dtsx"].reason == SkipReason.FILE_TOO_LARGE


def test_plugin_archive_upload_supports_neutral_assessment_api(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    fixture = (
        Path(__file__).parents[1]
        / "examples"
        / "plugins"
        / "synthetic-ssis"
        / "fixtures"
        / "synthetic-package.dtsx"
    )
    output = io.BytesIO()
    with ZipFile(output, "w") as archive:
        archive.writestr("package.dtsx", fixture.read_bytes())
    with RunService(tmp_path / "state", source_registry=_synthetic_ssis_registry()) as service:
        monkeypatch.setattr(app.state, "run_service", service, raising=False)
        with TestClient(app, base_url="http://127.0.0.1") as client:
            response = client.post(
                "/api/snapshots/upload",
                data={"mode": "zip"},
                files=[("files", ("source.zip", output.getvalue(), "application/zip"))],
            )
            assert response.status_code == 200
            assert response.json()["workflows"][0]["source_platform"] == "ssis"
            run = client.post("/api/runs", json={"snapshot_id": response.json()["snapshot_id"]})
            assert run.status_code == 202
            identity = run.json()["id"]
            for _ in range(100):
                result = client.get(f"/api/runs/{identity}").json()
                if result["status"] in {"completed", "failed", "cancelled"}:
                    break
                time.sleep(0.03)
            assert result["status"] == "completed"
            assert result["result"]["failed_count"] == 1
            neutral = client.get(f"/api/runs/{identity}/neutral-assessment")
            assert neutral.status_code == 200
            assert neutral.json()["assessments"][0]["unknown_components"] == [
                "ssis_unverified_task"
            ]


def test_neutral_cli_assesses_plugin_archive(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    fixture = (
        Path(__file__).parents[1]
        / "examples"
        / "plugins"
        / "synthetic-ssis"
        / "fixtures"
        / "synthetic-package.dtsx"
    )
    archive_path = tmp_path / "source.zip"
    with ZipFile(archive_path, "w") as archive:
        archive.writestr("package.dtsx", fixture.read_bytes())
    cli_module = import_module("accelerator.cli.app")
    sources = _synthetic_ssis_registry()
    monkeypatch.setattr(
        cli_module,
        "PortfolioAssessmentApplication",
        lambda: PortfolioAssessmentApplication(source_registry=sources),
    )
    result = CliRunner().invoke(cli_module.app, ["assess-neutral", str(archive_path)])
    assert result.exit_code == 0, result.output
    assessment = json.loads(result.stdout)
    assert assessment["workflow_count"] == 1
    assert assessment["assessments"][0]["unknown_components"] == ["ssis_unverified_task"]
    assert assessment["workflows"][0]["parser_version"] == sources.adapters[0].parser_version


def test_plugin_discovery_rejects_invalid_extension() -> None:
    class InvalidExtensionAdapter(FakeAdapter):
        supported_extensions = ("../unsafe",)

    registry = SourceAdapterRegistry(
        (InvalidExtensionAdapter("invalid", "ssis", "SSIS", 100, b"ssis"),)
    )
    with pytest.raises(ValueError, match="invalid source extension"):
        registry.file_extensions()


def test_external_file_adapter_cannot_claim_uncertified_builtin_source(tmp_path: Path) -> None:
    class FileAdapter(FakeAdapter):
        supported_extensions = (".dtsx",)

    source = tmp_path / "source.dtsx"
    source.write_bytes(b"synthetic ssis marker")
    registry = SourceAdapterRegistry(
        (FileAdapter("external", SourcePlatform.ALTERYX, "Alteryx", 100, b"ssis"),)
    )
    summary = DiscoveryService(source_registry=registry).discover(source)
    assert summary.workflow_count == 0
    assert "built-in source identity" in summary.skipped[0].detail


def test_plugin_discovery_reports_unknown_and_ambiguous_files(tmp_path: Path) -> None:
    class FileAdapter(FakeAdapter):
        supported_extensions = (".dtsx",)

    source = tmp_path / "source.dtsx"
    source.write_bytes(b"synthetic ssis marker")
    without_plugin = DiscoveryService().discover(source)
    assert without_plugin.skipped[0].reason == SkipReason.UNSUPPORTED_EXTENSION

    adapters = (
        FileAdapter("first", "ssis", "SSIS", 100, b"ssis"),
        FileAdapter("second", "ssis", "SSIS", 100, b"ssis"),
    )
    ambiguous = DiscoveryService(source_registry=SourceAdapterRegistry(adapters)).discover(source)
    assert ambiguous.workflow_count == 0
    assert "Ambiguous source format" in ambiguous.skipped[0].detail

    source.write_bytes(b"unknown")
    unknown = DiscoveryService(source_registry=SourceAdapterRegistry(adapters)).discover(source)
    assert unknown.workflow_count == 0
    assert "No source adapter recognized" in unknown.skipped[0].detail


def test_external_source_snapshot_is_bound_to_adapter_identity_and_version(
    tmp_path: Path,
) -> None:
    class FileAdapter(FakeAdapter):
        supported_extensions = (".dtsx",)

    source = tmp_path / "source.dtsx"
    source.write_bytes(b"synthetic ssis marker")
    first_adapter = FileAdapter("first", "ssis", "SSIS", 100, b"ssis")
    second_adapter = FileAdapter("second", "ssis", "SSIS", 100, b"ssis")
    root = tmp_path / "state"
    with RunService(root, source_registry=SourceAdapterRegistry((first_adapter,))) as service:
        first = service.preview(source)
        run = service.create_run(first.snapshot_id)

    with RunService(root, source_registry=SourceAdapterRegistry((second_adapter,))) as service:
        second = service.preview(source)
        assert second.snapshot_id != first.snapshot_id
        with pytest.raises(ValueError, match="Confirmed source adapter changed"):
            service.create_run(first.snapshot_id)
        service.execute(run.id)
        assert service.get_run(run.id).status == "failed"
        assert "source adapter" in (service.get_run(run.id).error or "")

    upgraded = FileAdapter("first", "ssis", "SSIS", 100, b"ssis", adapter_version="2.0")
    with (
        RunService(root, source_registry=SourceAdapterRegistry((upgraded,))) as service,
        pytest.raises(ValueError, match="Confirmed source adapter changed"),
    ):
        service.create_run(first.snapshot_id)


@pytest.mark.parametrize("version_field", ["parser_version", "registry_version", "rules_version"])
def test_external_source_snapshot_rejects_changed_component_version(
    tmp_path: Path, version_field: str
) -> None:
    class FileAdapter(FakeAdapter):
        supported_extensions = (".dtsx",)

    source = tmp_path / "source.dtsx"
    source.write_bytes(b"synthetic ssis marker")
    adapter = FileAdapter("first", "ssis", "SSIS", 100, b"ssis")
    root = tmp_path / "state"
    with RunService(root, source_registry=SourceAdapterRegistry((adapter,))) as service:
        first = service.preview(source)
        run = service.create_run(first.snapshot_id)

    updated = _with_version(adapter, version_field, "2.0")
    with RunService(root, source_registry=SourceAdapterRegistry((updated,))) as service:
        second = service.preview(source)
        assert second.snapshot_id != first.snapshot_id
        with pytest.raises(ValueError, match="Confirmed source adapter changed"):
            service.create_run(first.snapshot_id)
        service.execute(run.id)
        assert service.get_run(run.id).status == "failed"
        assert "source adapter" in (service.get_run(run.id).error or "")


def test_legacy_external_snapshot_requires_new_preview(tmp_path: Path) -> None:
    class FileAdapter(FakeAdapter):
        supported_extensions = (".dtsx",)

    source = tmp_path / "source.dtsx"
    source.write_bytes(b"synthetic ssis marker")
    adapter = FileAdapter("first", "ssis", "SSIS", 100, b"ssis")
    with RunService(
        tmp_path / "state", source_registry=SourceAdapterRegistry((adapter,))
    ) as service:
        preview = service.preview(source)
        old_item = preview.workflows[0].model_copy(
            update={"parser_version": None, "registry_version": None, "rules_version": None}
        )
        old_id = _snapshot_id([old_item])
        legacy = preview.model_copy(update={"snapshot_id": old_id, "workflows": [old_item]})
        with service._connection() as connection:
            connection.execute(
                "INSERT INTO snapshots VALUES (?, ?)", (old_id, legacy.model_dump_json())
            )
        with pytest.raises(ValueError, match="Confirmed source adapter changed"):
            service.create_run(old_id)
        assert service.create_run(preview.snapshot_id).status == "queued"


@pytest.mark.parametrize(
    "version_field", ["adapter_version", "parser_version", "registry_version", "rules_version"]
)
def test_external_source_discovery_rejects_empty_versions(
    tmp_path: Path, version_field: str
) -> None:
    class FileAdapter(FakeAdapter):
        supported_extensions = (".dtsx",)

    source = tmp_path / "source.dtsx"
    source.write_bytes(b"synthetic ssis marker")
    adapter = _with_version(FileAdapter("first", "ssis", "SSIS", 100, b"ssis"), version_field, "")
    summary = DiscoveryService(source_registry=SourceAdapterRegistry((adapter,))).discover(source)
    assert summary.workflow_count == 0
    assert "version metadata must not be empty" in summary.skipped[0].detail


def test_synthetic_ssis_plugin_rejects_unsafe_or_incomplete_xml(tmp_path: Path) -> None:
    registry = _synthetic_ssis_registry()
    source = tmp_path / "synthetic.dtsx"
    source.write_text('<!DOCTYPE x [<!ENTITY x "unsafe">]><x/>', encoding="utf-8")
    with pytest.raises(ValueError, match="unsafe synthetic SSIS XML"):
        registry.detect(source, source.name)
    source.write_text(
        '<DTS:Executable xmlns:DTS="www.microsoft.com/SqlServer/Dts" '
        'DTS:ExecutableType="SSIS.Package.2"/>',
        encoding="utf-8",
    )
    detected = registry.detect(source, source.name)
    with pytest.raises(ValueError, match="require DTSID and ObjectName"):
        registry.parse(source, detected.match)


def test_synthetic_ssis_plugin_enforces_file_size_limit(tmp_path: Path) -> None:
    registry = _synthetic_ssis_registry()
    source = tmp_path / "synthetic.dtsx"
    root = (
        b'<DTS:Executable xmlns:DTS="www.microsoft.com/SqlServer/Dts" '
        b'DTS:ExecutableType="SSIS.Package.2" DTS:DTSID="package" '
        b'DTS:ObjectName="Synthetic"/>'
    )
    limit = 5 * 1024 * 1024
    source.write_bytes(root + b" " * (limit - len(root)))
    detected = registry.detect(source, source.name)
    assert registry.parse(source, detected.match).assets[0].name == "Synthetic"
    source.write_bytes(root + b" " * (limit + 1 - len(root)))
    with pytest.raises(ValueError, match="exceeds the 5 MiB limit"):
        registry.detect(source, source.name)


def test_synthetic_ssis_plugin_enforces_executable_limit(tmp_path: Path) -> None:
    registry = _synthetic_ssis_registry()
    source = tmp_path / "synthetic.dtsx"
    start = (
        '<DTS:Executable xmlns:DTS="www.microsoft.com/SqlServer/Dts" '
        'DTS:ExecutableType="SSIS.Package.2" DTS:DTSID="package" '
        'DTS:ObjectName="Synthetic"><DTS:Executables>'
    )
    end = "</DTS:Executables></DTS:Executable>"
    tasks = "".join(
        f'<DTS:Executable DTS:DTSID="task-{index}" DTS:ObjectName="Task"/>'
        for index in range(9_999)
    )
    source.write_text(start + tasks + end, encoding="utf-8")
    detected = registry.detect(source, source.name)
    graph = registry.parse(source, detected.match).assets[0].orchestration_graph
    assert graph is not None and len(graph.nodes) == 10_000
    source.write_text(
        start + tasks + '<DTS:Executable DTS:DTSID="extra" DTS:ObjectName="Task"/>' + end,
        encoding="utf-8",
    )
    detected = registry.detect(source, source.name)
    with pytest.raises(ValueError, match="exceeds the executable limit"):
        registry.parse(source, detected.match)

