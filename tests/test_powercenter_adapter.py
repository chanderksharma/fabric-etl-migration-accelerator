"""PowerCenter XML adapter tests."""

from pathlib import Path

from etl_migration_core.contracts.ir import AssetType, GraphKind, SourcePlatform
from etl_migration_core.sources.informatica_powercenter import PowerCenterSourceAdapter

FIXTURE = Path(__file__).parent / "fixtures" / "powercenter" / "basic_repository.xml"


def test_powercenter_adapter_parses_mapping_and_workflow() -> None:
    adapter = PowerCenterSourceAdapter()

    match = adapter.probe(FIXTURE, FIXTURE.name)
    assert match is not None
    package = adapter.parse(FIXTURE, match)

    assert package.source_platform is SourcePlatform.INFORMATICA_POWERCENTER
    assert package.product_version == "10.5"
    workflow = next(asset for asset in package.assets if asset.asset_type is AssetType.WORKFLOW)
    assert workflow.folder == "Sales"
    assert workflow.orchestration_graph is not None
    assert workflow.orchestration_graph.kind is GraphKind.ORCHESTRATION
    assert {node.native_id for node in workflow.orchestration_graph.nodes} == {
        "Start",
        "s_orders",
    }
    assert workflow.mapping_graphs[0].kind is GraphKind.MAPPING
    assert {node.native_id for node in workflow.mapping_graphs[0].nodes} == {
        "Orders",
        "SQ_Orders",
        "FLT_Valid",
        "OrdersCurated",
    }
    assert [schedule.name for schedule in workflow.schedules] == ["Daily"]


def test_powercenter_adapter_rejects_non_powercenter_xml(tmp_path: Path) -> None:
    source = tmp_path / "workflow.xml"
    source.write_text("<NotPowerCenter/>", encoding="utf-8")

    assert PowerCenterSourceAdapter().probe(source, source.name) is None


def test_powercenter_adapter_links_workflow_nested_session_to_mapping(
    tmp_path: Path,
) -> None:
    source = tmp_path / "nested-session.xml"
    source.write_text(
        """<?xml version="1.0"?>
<POWERMART REPOSITORY_VERSION="10.5">
  <REPOSITORY NAME="repo" VERSION="1">
    <FOLDER NAME="Sales">
      <SOURCE NAME="Orders"/>
      <TARGET NAME="Curated"/>
      <MAPPING NAME="m_orders">
        <TRANSFORMATION NAME="RTR_Orders" TYPE="Router">
          <GROUP NAME="INPUT" TYPE="INPUT"/>
          <GROUP NAME="VALID" TYPE="OUTPUT" EXPRESSION="ISNULL(Error)"/>
          <TRANSFORMFIELD NAME="Error" PORTTYPE="INPUT" GROUP="INPUT"/>
          <TRANSFORMFIELD NAME="OrderId1" PORTTYPE="OUTPUT"
            GROUP="VALID" REF_FIELD="OrderId"/>
        </TRANSFORMATION>
        <TRANSFORMATION NAME="AGG_Orders" TYPE="Aggregator">
          <TRANSFORMFIELD NAME="OrderId1" PORTTYPE="INPUT/OUTPUT"
            EXPRESSION="OrderId1" EXPRESSIONTYPE="GROUPBY"/>
          <METADATAEXTENSION NAME="SQL_Query" VALUE="SELECT 1"/>
        </TRANSFORMATION>
        <INSTANCE NAME="Orders" TYPE="SOURCE"/>
        <INSTANCE NAME="RTR_Orders" TYPE="TRANSFORMATION"
          TRANSFORMATION_NAME="RTR_Orders"/>
        <INSTANCE NAME="AGG_Orders" TYPE="TRANSFORMATION"
          TRANSFORMATION_NAME="AGG_Orders"/>
        <INSTANCE NAME="Curated" TYPE="TARGET"/>
        <CONNECTOR FROMINSTANCE="Orders" TOINSTANCE="RTR_Orders"/>
        <CONNECTOR FROMINSTANCE="RTR_Orders" FROMFIELD="OrderId1"
          TOINSTANCE="AGG_Orders" TOFIELD="OrderId1"/>
        <CONNECTOR FROMINSTANCE="AGG_Orders" TOINSTANCE="Curated"/>
      </MAPPING>
      <WORKFLOW NAME="wf_orders">
        <SESSION NAME="s_orders" MAPPINGNAME="m_orders"/>
        <TASKINSTANCE NAME="Start" TASKNAME="Start" TASKTYPE="Start"/>
        <TASKINSTANCE NAME="s_orders" TASKNAME="s_orders" TASKTYPE="Session"/>
        <WORKFLOWLINK FROMTASK="Start" TOTASK="s_orders"/>
      </WORKFLOW>
    </FOLDER>
  </REPOSITORY>
</POWERMART>
""",
        encoding="utf-8",
    )
    adapter = PowerCenterSourceAdapter()
    match = adapter.probe(source, source.name)
    assert match is not None

    package = adapter.parse(source, match)

    assert len(package.assets) == 1
    workflow = package.assets[0]
    assert workflow.name == "wf_orders"
    assert [graph.kind for graph in workflow.mapping_graphs] == [GraphKind.MAPPING]
    nodes = {node.name: node for node in workflow.mapping_graphs[0].nodes}
    router = nodes["RTR_Orders"]
    assert router.properties["router_groups"] == [
        {"name": "INPUT", "type": "INPUT", "expression": ""},
        {"name": "VALID", "type": "OUTPUT", "expression": "ISNULL(Error)"},
    ]
    assert router.properties["port_groups"] == {
        "Error": "INPUT",
        "OrderId1": "VALID",
    }
    assert router.properties["port_ref_fields"] == {"OrderId1": "OrderId"}
    assert nodes["AGG_Orders"].properties["port_expression_types"] == {
        "OrderId1": "GROUPBY"
    }
    assert nodes["AGG_Orders"].properties["metadata_extensions"] == {
        "SQL_Query": "SELECT 1"
    }

