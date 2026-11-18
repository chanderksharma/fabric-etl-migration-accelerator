"""IICS/IDMC export package adapter tests."""

import zipfile
from pathlib import Path

from accelerator.etl_ir import AssetType, GraphKind, SourcePlatform
from accelerator.sources.informatica_idmc import IdmcSourceAdapter

FIXTURE = Path(__file__).parent / "fixtures" / "idmc" / "basic_export"


def test_idmc_adapter_parses_export_directory() -> None:
    adapter = IdmcSourceAdapter()

    match = adapter.probe(FIXTURE, "basic_export")
    assert match is not None
    package = adapter.parse(FIXTURE, match)

    assert package.source_platform is SourcePlatform.INFORMATICA_IDMC
    assert package.export_version == "3"
    assert {asset.asset_type for asset in package.assets} == {
        AssetType.MAPPING,
        AssetType.MAPPING_TASK,
        AssetType.TASKFLOW,
    }
    mapping = next(asset for asset in package.assets if asset.asset_type is AssetType.MAPPING)
    assert mapping.mapping_graphs[0].kind is GraphKind.MAPPING
    taskflow = next(asset for asset in package.assets if asset.asset_type is AssetType.TASKFLOW)
    assert taskflow.orchestration_graph is not None
    assert taskflow.orchestration_graph.kind is GraphKind.ORCHESTRATION


def test_idmc_adapter_parses_equivalent_zip_package(tmp_path: Path) -> None:
    archive = tmp_path / "idmc-export.zip"
    with zipfile.ZipFile(archive, "w", compression=zipfile.ZIP_DEFLATED) as zip_package:
        for path in FIXTURE.rglob("*"):
            if path.is_file():
                zip_package.write(path, path.relative_to(FIXTURE).as_posix())
    adapter = IdmcSourceAdapter()

    match = adapter.probe(archive, archive.name)
    assert match is not None
    parsed = adapter.parse(archive, match)

    assert len(parsed.assets) == 3
    assert parsed.export_id == archive.name

