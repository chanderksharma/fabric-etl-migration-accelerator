"""Canonical ETL intermediate representation contracts."""

import pytest
from pydantic import ValidationError

from accelerator.etl_ir import (
    IR_VERSION,
    AssetType,
    EtlAsset,
    EtlConnectionRef,
    EtlEdge,
    EtlGraph,
    EtlNode,
    EtlPackage,
    GraphKind,
    NodeKind,
    SourcePlatform,
)


def test_etl_package_keeps_mapping_and_orchestration_graphs_separate() -> None:
    mapping = EtlGraph(
        kind=GraphKind.MAPPING,
        nodes=(
            EtlNode(
                native_id="src",
                name="Orders",
                operation="source",
                kind=NodeKind.SOURCE,
            ),
            EtlNode(
                native_id="flt",
                name="Valid orders",
                operation="filter",
                kind=NodeKind.TRANSFORMATION,
            ),
        ),
        edges=(EtlEdge(source="src", target="flt"),),
    )
    orchestration = EtlGraph(
        kind=GraphKind.ORCHESTRATION,
        nodes=(
            EtlNode(
                native_id="session",
                name="Load orders",
                operation="mapping_task",
                kind=NodeKind.TASK,
            ),
        ),
    )
    package = EtlPackage(
        source_platform=SourcePlatform.INFORMATICA_POWERCENTER,
        source_product="PowerCenter",
        product_version="10.5",
        export_id="repository-export",
        assets=(
            EtlAsset(
                native_id="wf_orders",
                name="wf_orders",
                asset_type=AssetType.WORKFLOW,
                folder="Sales",
                mapping_graphs=(mapping,),
                orchestration_graph=orchestration,
            ),
        ),
    )

    assert package.ir_version == IR_VERSION
    assert package.assets[0].mapping_graphs[0].kind is GraphKind.MAPPING
    assert package.assets[0].orchestration_graph is not None
    assert package.assets[0].orchestration_graph.kind is GraphKind.ORCHESTRATION
    with pytest.raises(ValidationError):
        package.source_product = "changed"


def test_graph_rejects_duplicate_nodes_and_unknown_edges() -> None:
    node = EtlNode(
        native_id="1",
        name="Source",
        operation="source",
        kind=NodeKind.SOURCE,
    )
    with pytest.raises(ValidationError, match="duplicate node"):
        EtlGraph(kind=GraphKind.MAPPING, nodes=(node, node))
    with pytest.raises(ValidationError, match="unknown node"):
        EtlGraph(
            kind=GraphKind.MAPPING,
            nodes=(node,),
            edges=(EtlEdge(source="1", target="missing"),),
        )


@pytest.mark.parametrize(
    "property_name",
    ["password", "clientSecret", "access_token", "accountKey"],
)
def test_connection_references_reject_secret_properties(property_name: str) -> None:
    with pytest.raises(ValidationError, match="credential"):
        EtlConnectionRef(
            native_id="connection-1",
            name="Source",
            kind="Sql",
            properties={property_name: "should-not-be-stored"},
        )

