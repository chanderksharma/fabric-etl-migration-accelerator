"""Alteryx adapter compatibility tests."""

from pathlib import Path

from accelerator.etl_ir import AssetType, GraphKind, SourcePlatform
from accelerator.sources.alteryx import AlteryxSourceAdapter


def test_alteryx_adapter_detects_and_normalizes_existing_workflow() -> None:
    source = (
        Path(__file__).parents[1]
        / "alteryx-workflows"
        / "11_multi_container_reconciliation.yxmd"
    )
    adapter = AlteryxSourceAdapter()

    match = adapter.probe(source, source.name)
    assert match is not None
    package = adapter.parse(source, match)

    assert package.source_platform is SourcePlatform.ALTERYX
    assert package.source_product == "Alteryx Designer"
    assert package.assets[0].asset_type is AssetType.WORKFLOW
    assert package.assets[0].mapping_graphs[0].kind is GraphKind.MAPPING
    assert len(package.assets[0].mapping_graphs[0].nodes) == 39
    assert len(package.assets[0].mapping_graphs[0].edges) == 30
    assert [container.name for container in package.assets[0].mapping_graphs[0].containers] == [
        "00 Source Files",
        "01 Ledger Alpha and Beta",
        "02 Reference Enrichment",
        "03 Settlement Reconciliation",
        "04 Final Outputs",
        "05 Destinations",
    ]

