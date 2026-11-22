"""Standalone tests for the etl-portfolio-assessment PyPI package."""

from __future__ import annotations

import json
from pathlib import Path

from etl_migration_core.contracts.ir import (
    EXTENSIBLE_SOURCE_IR_VERSION,
    AssetType,
    EtlAsset,
    EtlGraph,
    EtlNode,
    EtlPackage,
    GraphKind,
    NodeKind,
    SourcePlatform,
)
from etl_portfolio_assessment.assessment.engine import assess_package_neutral
from etl_portfolio_assessment.assessment.workload_profile import extract_workload_profile
from etl_portfolio_assessment.service.application import PortfolioAssessmentApplication
from etl_portfolio_assessment.service.stdio import main as assess_stdio_main


def test_portfolio_assessment_application_and_stdio(
    capsys: object,
) -> None:
    sample_dir = Path(__file__).parents[3] / "alteryx-workflows"
    app = PortfolioAssessmentApplication()

    preview = app.preview(sample_dir)
    assert preview.workflow_count > 0

    estate = app.assess_neutral(sample_dir)
    assert estate.failed_count == 0
    assert estate.workflow_count == preview.workflow_count
    payload = estate.model_dump_json().casefold()
    assert "dataflow gen2" not in payload
    assert "f-sku" not in payload

    evidence = app.inspect_evidence(sample_dir)
    assert len(evidence) == preview.workflow_count

    exit_code = assess_stdio_main(["assess", str(sample_dir)])
    assert exit_code in (0, 1)
    assert assess_stdio_main(["preview", str(sample_dir)]) == 0
    assert assess_stdio_main(["evidence", str(sample_dir)]) == 0
    _ = capsys
    parsed = json.loads(estate.model_dump_json())
    assert parsed["workflow_count"] == preview.workflow_count


def test_neutral_assessment_classifies_issues_per_node() -> None:
    nodes = (
        EtlNode(native_id="good", name="Good", operation="filter", kind=NodeKind.TRANSFORMATION),
        EtlNode(
            native_id="issue",
            name="Unresolved",
            operation="filter",
            kind=NodeKind.TRANSFORMATION,
            issues=("Unresolved expression",),
        ),
    )
    asset = EtlAsset(
        native_id="mapping",
        name="Mapping",
        asset_type=AssetType.MAPPING,
        mapping_graphs=(EtlGraph(kind=GraphKind.MAPPING, nodes=nodes),),
    )
    package = EtlPackage(
        source_platform=SourcePlatform.INFORMATICA_IDMC,
        source_product="Synthetic IDMC",
        export_id="synthetic",
        assets=(asset,),
    )

    assessment = assess_package_neutral(package)[0]

    assert {(item.operation, item.classification, item.count) for item in assessment.inventory} == {
        ("filter", "manual", 1),
        ("filter", "tabular", 1),
    }
    assert assessment.component_count == 2
    assert assessment.complexity_score == 7
    assert assessment.intrinsic_effort_days == 1.5
    assert assessment.unknown_components == ("filter",)


def test_neutral_assessment_flags_unrecognized_operations() -> None:
    asset = EtlAsset(
        native_id="mapping",
        name="Mapping",
        asset_type=AssetType.MAPPING,
        mapping_graphs=(
            EtlGraph(
                kind=GraphKind.MAPPING,
                nodes=(
                    EtlNode(
                        native_id="custom",
                        name="Unrecognized",
                        operation="unrecognized_custom_task",
                        kind=NodeKind.TRANSFORMATION,
                    ),
                ),
            ),
        ),
    )
    package = EtlPackage(
        source_platform=SourcePlatform.INFORMATICA_IDMC,
        source_product="Synthetic IDMC",
        export_id="synthetic",
        assets=(asset,),
    )

    assessment = assess_package_neutral(package)[0]

    assert assessment.inventory[0].classification == "manual"
    assert assessment.unknown_components == ("unrecognized_custom_task",)
    assert assessment.wave_tier == "Wave 4"


def test_unknown_source_uses_generic_neutral_profile() -> None:
    asset = EtlAsset(native_id="asset", name="Synthetic", asset_type=AssetType.MAPPING)
    package = EtlPackage(
        ir_version=EXTENSIBLE_SOURCE_IR_VERSION,
        source_platform="ssis",
        source_product="Synthetic SSIS",
        export_id="synthetic",
        assets=(asset,),
    )

    assert assess_package_neutral(package)[0].source_platform == "ssis"
    profile = extract_workload_profile(package, asset)
    assert profile.source_platform == "ssis"
    assert profile.profile_kind == "generic"
