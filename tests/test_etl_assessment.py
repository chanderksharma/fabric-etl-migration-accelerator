"""Source-neutral ETL assessment tests."""

from pathlib import Path

from accelerator.etl_assessment import assess_package
from accelerator.etl_ir import (
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
from accelerator.sources.informatica_idmc import IdmcSourceAdapter
from accelerator.sources.informatica_powercenter import PowerCenterSourceAdapter

FIXTURES = Path(__file__).parent / "fixtures"


def test_assessment_counts_stage_links_not_field_connectors() -> None:
    graph = EtlGraph(
        kind=GraphKind.MAPPING,
        nodes=(
            EtlNode(
                native_id="src",
                name="Source",
                operation="source",
                kind=NodeKind.SOURCE,
            ),
            EtlNode(
                native_id="tgt",
                name="Target",
                operation="target",
                kind=NodeKind.TARGET,
            ),
        ),
        edges=(
            EtlEdge(
                source="src",
                target="tgt",
                source_port="CustomerId",
                target_port="CustomerId",
            ),
            EtlEdge(
                source="src",
                target="tgt",
                source_port="CustomerName",
                target_port="CustomerName",
            ),
        ),
    )
    asset = EtlAsset(
        native_id="m_customers",
        name="m_customers",
        asset_type=AssetType.MAPPING,
        mapping_graphs=(graph,),
    )
    package = EtlPackage(
        source_platform=SourcePlatform.INFORMATICA_POWERCENTER,
        source_product="Informatica PowerCenter",
        export_id="repo",
        assets=(asset,),
    )

    assessment = assess_package(package)[0]

    assert assessment.connection_count == 1
    assert assessment.complexity_score == 3
    assert assessment.estimated_effort_days == 0.5


def test_informatica_effort_is_capped_at_twenty_one_days() -> None:
    graph = EtlGraph(
        kind=GraphKind.MAPPING,
        nodes=tuple(
            EtlNode(
                native_id=f"custom-{index}",
                name=f"Custom {index}",
                operation=f"custom_{index}",
                kind=NodeKind.TRANSFORMATION,
            )
            for index in range(30)
        ),
    )
    asset = EtlAsset(
        native_id="m_custom",
        name="m_custom",
        asset_type=AssetType.MAPPING,
        mapping_graphs=(graph,),
    )
    package = EtlPackage(
        source_platform=SourcePlatform.INFORMATICA_POWERCENTER,
        source_product="Informatica PowerCenter",
        export_id="repo",
        assets=(asset,),
    )

    assessment = assess_package(package)[0]

    assert assessment.estimated_effort_days == 21.0


def test_powercenter_assessment_routes_mapping_and_workflow_components() -> None:
    source = FIXTURES / "powercenter" / "basic_repository.xml"
    adapter = PowerCenterSourceAdapter()
    match = adapter.probe(source, source.name)
    assert match is not None

    assessments = assess_package(adapter.parse(source, match))

    workflow = next(item for item in assessments if item.name == "wf_orders")
    assert workflow.source_platform == "informatica_powercenter"
    assert workflow.component_count == 6
    assert workflow.connection_count == 4
    assert workflow.recommended_target == "Mixed Fabric solution"
    assert workflow.target_components == ("Dataflow Gen2", "Fabric Pipeline")
    assert workflow.unsupported_components == ()
    assert {item.operation for item in workflow.inventory} == {
        "filter",
        "session",
        "source",
        "source_qualifier",
        "start",
        "target",
    }


def test_idmc_assessment_covers_mapping_task_and_taskflow() -> None:
    source = FIXTURES / "idmc" / "basic_export"
    adapter = IdmcSourceAdapter()
    match = adapter.probe(source, "basic_export")
    assert match is not None

    assessments = assess_package(adapter.parse(source, match))

    mapping = next(item for item in assessments if item.name == "m_orders")
    assert mapping.recommended_target == "Dataflow Gen2"
    assert mapping.target_components == ("Dataflow Gen2",)
    task = next(item for item in assessments if item.name == "mt_orders")
    assert task.recommended_target == "Fabric Pipeline"
    taskflow = next(item for item in assessments if item.name == "tf_orders")
    assert taskflow.recommended_target == "Fabric Pipeline"
    assert taskflow.unsupported_components == ()

