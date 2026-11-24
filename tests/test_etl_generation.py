"""Informatica-to-Fabric compiler contracts."""

import ast
import json
from pathlib import Path

import pytest

from etl_migration_core.contracts.ir import (
    AssetType,
    EtlAsset,
    EtlEdge,
    EtlGraph,
    EtlNode,
    EtlPackage,
    EtlPort,
    GraphKind,
    NodeKind,
    SourcePlatform,
)
from etl_migration_core.sources.informatica_idmc import IdmcSourceAdapter
from etl_migration_core.sources.informatica_powercenter import PowerCenterSourceAdapter
from etl_target_fabric.assessment.ir_assessment import assess_package
from etl_target_fabric.compilers.ir import (
    compile_asset,
    compile_asset_targets,
)
from etl_target_fabric.evaluation import apply_native_route

FIXTURES = Path(__file__).parent / "fixtures"


def _literal_package(expression: str) -> tuple[EtlPackage, EtlAsset]:
    graph = EtlGraph(
        kind=GraphKind.MAPPING,
        nodes=(
            EtlNode(native_id="src", name="Orders", operation="source", kind=NodeKind.SOURCE),
            EtlNode(
                native_id="exp",
                name="Literals",
                operation="expression",
                kind=NodeKind.TRANSFORMATION,
                ports=(
                    EtlPort(
                        name="Label",
                        direction="output",
                        data_type="string",
                        expression=expression,
                    ),
                ),
            ),
            EtlNode(native_id="tgt", name="Out", operation="target", kind=NodeKind.TARGET),
        ),
        edges=(
            EtlEdge(source="src", target="exp", source_port="Label", target_port="Label"),
            EtlEdge(source="exp", target="tgt", source_port="Label", target_port="Label"),
        ),
    )
    asset = EtlAsset(
        native_id="m_literals",
        name="m_literals",
        asset_type=AssetType.MAPPING,
        mapping_graphs=(graph,),
    )
    package = EtlPackage(
        source_platform=SourcePlatform.INFORMATICA_POWERCENTER,
        source_product="Informatica PowerCenter",
        export_id="repo",
        assets=(asset,),
    )
    return package, asset


def test_powercenter_text_literals_compile_to_well_formed_m() -> None:
    from etl_target_fabric.compilers.m_literals import m_text_is_well_formed

    for expression, expected in (
        ("'Café'", '"Café"'),
        ("'\"'", '""""'),
        ("'#(lf)'", '"#(#)(lf)"'),
    ):
        package, asset = _literal_package(expression)
        candidate = compile_asset(package, asset, "dataflow")
        assert candidate.validation_state == "generated_unvalidated"
        assert expected in candidate.code
        assert m_text_is_well_formed(candidate.code)
    assert m_text_is_well_formed("shared Rows = #table(type table [Id = number], {{1}})")


def test_malformed_power_query_is_scaffolded_before_publish(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(
        "etl_target_fabric.compilers.ir.m_text_is_well_formed",
        lambda _code: False,
    )
    package, asset = _literal_package("'ok'")

    dataflow = compile_asset(package, asset, "dataflow")
    pipeline = compile_asset(package, asset, "pipeline")

    assert dataflow.validation_state == "scaffold"
    assert dataflow.deployable is False
    assert "Generated Power Query M is not well-formed" in dataflow.diagnostics
    assert pipeline.deployable is False


def test_expression_mapping_compiles_bounded_powercenter_functions() -> None:
    graph = EtlGraph(
        kind=GraphKind.MAPPING,
        nodes=(
            EtlNode(
                native_id="src",
                name="Orders",
                operation="source",
                kind=NodeKind.SOURCE,
            ),
            EtlNode(
                native_id="exp",
                name="Clean Orders",
                operation="expression",
                kind=NodeKind.TRANSFORMATION,
                ports=(
                    EtlPort(name="Account", direction="input", data_type="string"),
                    EtlPort(
                        name="CleanAccount",
                        direction="output",
                        data_type="string",
                        expression="LTRIM(RTRIM(Account))",
                    ),
                    EtlPort(
                        name="Total",
                        direction="output",
                        data_type="decimal",
                        expression="Amount + Tax",
                    ),
                    EtlPort(
                        name="RunDate",
                        direction="output",
                        data_type="date/time",
                        expression="to_date(BusinessDate,'DD-MON-YYYY')",
                    ),
                    EtlPort(
                        name="CreatedAt",
                        direction="output",
                        data_type="date/time",
                        expression="SYSDATE",
                    ),
                    EtlPort(
                        name="Owner",
                        direction="output",
                        data_type="string",
                        expression="'HUB_OWNER'",
                    ),
                    EtlPort(
                        name="RecordType",
                        direction="output",
                        data_type="integer",
                        expression="1",
                    ),
                ),
            ),
            EtlNode(
                native_id="tgt",
                name="Curated Orders",
                operation="target",
                kind=NodeKind.TARGET,
            ),
        ),
        edges=(
            EtlEdge(
                source="src",
                target="exp",
                source_port="Account",
                target_port="Account",
            ),
            EtlEdge(
                source="src",
                target="exp",
                source_port="Amount",
                target_port="Amount",
            ),
            EtlEdge(
                source="exp",
                target="tgt",
                source_port="CleanAccount",
                target_port="Account",
            ),
            EtlEdge(
                source="exp",
                target="tgt",
                source_port="Total",
                target_port="Total",
            ),
        ),
    )
    asset = EtlAsset(
        native_id="m_orders",
        name="m_orders",
        asset_type=AssetType.MAPPING,
        mapping_graphs=(graph,),
    )
    package = EtlPackage(
        source_platform=SourcePlatform.INFORMATICA_POWERCENTER,
        source_product="Informatica PowerCenter",
        export_id="repo",
        assets=(asset,),
    )

    dataflow = compile_asset(package, asset, "dataflow")
    notebook = compile_asset(package, asset, "notebook")

    assert dataflow.deployable
    assert dataflow.definition_queries == ("SourceBindings", "curated_orders")
    assert 'Table.AddColumn(orders, "CleanAccount"' in dataflow.code
    assert "Text.Trim" in dataflow.code
    assert "Date.FromText" in dataflow.code
    assert "DateTime.LocalNow()" in dataflow.code
    assert '"HUB_OWNER"' in dataflow.code
    assert notebook.deployable
    assert '.withColumn("CleanAccount", F.trim(F.col("Account")))' in notebook.code
    assert 'F.to_date(F.col("BusinessDate"), "dd-MMM-yyyy")' in notebook.code
    assert 'F.col("Amount") + F.col("Tax")' in notebook.code
    assert "F.current_timestamp()" in notebook.code
    assert 'F.lit("HUB_OWNER")' in notebook.code
    assert "F.lit(1)" in notebook.code


def test_powercenter_date_and_path_expressions_compile_to_dataflow() -> None:
    graph = EtlGraph(
        kind=GraphKind.MAPPING,
        nodes=(
            EtlNode(
                native_id="src",
                name="Files",
                operation="source",
                kind=NodeKind.SOURCE,
            ),
            EtlNode(
                native_id="exp",
                name="Parse File Metadata",
                operation="expression",
                kind=NodeKind.TRANSFORMATION,
                ports=(
                    EtlPort(
                        name="File_Name",
                        direction="output",
                        expression=(
                            "SUBSTR(CurrentlyProcessedFileName,"
                            "INSTR(CurrentlyProcessedFileName,'/',-1,1)+1)"
                        ),
                    ),
                    EtlPort(
                        name="File_Date",
                        direction="output",
                        expression=(
                            "SUBSTR(CurrentlyProcessedFileName,"
                            "INSTR(CurrentlyProcessedFileName,'_',-1,1)+1,"
                            "INSTR(CurrentlyProcessedFileName,'.',1,1)-"
                            "INSTR(CurrentlyProcessedFileName,'_',-1,1)-1)"
                        ),
                    ),
                    EtlPort(
                        name="Date_FLAG",
                        direction="output",
                        expression="IS_DATE(File_Date,'YYYYMMDD')",
                    ),
                    EtlPort(
                        name="AUM_DATE",
                        direction="output",
                        expression=(
                            "IIF(Date_FLAG='1',"
                            "TRUNC(TO_DATE(File_Date,'YYYYMMDD'),'MM'),NULL)"
                        ),
                    ),
                    EtlPort(
                        name="AUM_DATE_TEXT",
                        direction="output",
                        expression="TO_CHAR(AUM_DATE,'YYYYMMDD')",
                    ),
                    EtlPort(
                        name="REJECT_REASON",
                        direction="output",
                        expression=(
                            "IIF(ISNULL(AUM_DATE),"
                            "'Invalid Date format',NULL)"
                        ),
                    ),
                ),
            ),
            EtlNode(
                native_id="tgt",
                name="Curated Files",
                operation="target",
                kind=NodeKind.TARGET,
            ),
        ),
        edges=(
            EtlEdge(source="src", target="exp"),
            EtlEdge(source="exp", target="tgt"),
        ),
    )
    asset = EtlAsset(
        native_id="m_files",
        name="m_files",
        asset_type=AssetType.MAPPING,
        mapping_graphs=(graph,),
    )
    package = EtlPackage(
        source_platform=SourcePlatform.INFORMATICA_POWERCENTER,
        source_product="Informatica PowerCenter",
        export_id="repo",
        assets=(asset,),
    )

    candidate = compile_asset(package, asset, "dataflow")

    assert candidate.deployable
    assert "List.Last(Text.Split" in candidate.code
    assert "Text.BeforeDelimiter" in candidate.code
    assert 'Format="yyyyMMdd"' in candidate.code
    assert "Date.StartOfMonth" in candidate.code
    assert 'Date.ToText(Date.From(Record.Field(_, "AUM_DATE")), "yyyyMMdd")' in (
        candidate.code
    )
    assert '"Invalid Date format"' in candidate.code


def test_router_and_groupby_aggregator_compile_to_dataflow() -> None:
    graph = EtlGraph(
        kind=GraphKind.MAPPING,
        nodes=(
            EtlNode(
                native_id="src",
                name="AUM Source",
                operation="source",
                kind=NodeKind.SOURCE,
            ),
            EtlNode(
                native_id="router",
                name="Route AUM",
                operation="router",
                kind=NodeKind.TRANSFORMATION,
                ports=(
                    EtlPort(name="REJECT_REASON", direction="input"),
                    EtlPort(name="SRC_TYPE", direction="input"),
                    EtlPort(name="File_Name3", direction="output"),
                    EtlPort(name="REJECT_REASON3", direction="output"),
                    EtlPort(name="FundGroup1", direction="output"),
                ),
                properties={
                    "router_groups": [
                        {
                            "name": "STG_DATA",
                            "type": "OUTPUT",
                            "expression": "ISNULL(REJECT_REASON)",
                        },
                        {
                            "name": "HFS_REJECTED_DATA",
                            "type": "OUTPUT",
                            "expression": (
                                "NOT(ISNULL(REJECT_REASON)) AND SRC_TYPE='HFS'"
                            ),
                        },
                    ],
                    "port_groups": {
                        "File_Name3": "HFS_REJECTED_DATA",
                        "REJECT_REASON3": "HFS_REJECTED_DATA",
                        "FundGroup1": "STG_DATA",
                    },
                    "port_ref_fields": {
                        "File_Name3": "File_Name",
                        "REJECT_REASON3": "REJECT_REASON",
                        "FundGroup1": "FundGroup",
                    },
                },
            ),
            EtlNode(
                native_id="agg",
                name="Distinct Rejects",
                operation="aggregator",
                kind=NodeKind.TRANSFORMATION,
                ports=(
                    EtlPort(
                        name="File_Name3",
                        direction="input_output",
                        expression="File_Name3",
                    ),
                    EtlPort(
                        name="REJECT_REASON3",
                        direction="input_output",
                        expression="REJECT_REASON3",
                    ),
                ),
                properties={
                    "port_expression_types": {
                        "File_Name3": "GROUPBY",
                        "REJECT_REASON3": "GROUPBY",
                    },
                },
            ),
            EtlNode(
                native_id="accepted",
                name="Accepted",
                operation="target",
                kind=NodeKind.TARGET,
            ),
            EtlNode(
                native_id="rejected",
                name="Rejected",
                operation="target",
                kind=NodeKind.TARGET,
            ),
        ),
        edges=(
            EtlEdge(source="src", target="router"),
            EtlEdge(
                source="router",
                target="accepted",
                source_port="FundGroup1",
            ),
            EtlEdge(
                source="router",
                target="agg",
                source_port="File_Name3",
            ),
            EtlEdge(
                source="router",
                target="agg",
                source_port="REJECT_REASON3",
            ),
            EtlEdge(source="agg", target="rejected"),
        ),
    )
    asset = EtlAsset(
        native_id="m_aum",
        name="m_aum",
        asset_type=AssetType.MAPPING,
        mapping_graphs=(graph,),
    )
    package = EtlPackage(
        source_platform=SourcePlatform.INFORMATICA_POWERCENTER,
        source_product="Informatica PowerCenter",
        export_id="repo",
        assets=(asset,),
    )

    candidate = compile_asset(package, asset, "dataflow")
    notebook = compile_asset(package, asset, "notebook")

    assert candidate.deployable
    assert candidate.definition_queries == (
        "SourceBindings",
        "aum_source",
        "accepted",
        "rejected",
    )
    assert "Table.SelectRows" in candidate.code
    assert 'Record.Field(_, "REJECT_REASON") = null' in candidate.code
    assert 'Record.Field(_, "SRC_TYPE") = "HFS"' in candidate.code
    assert 'Table.AddColumn(aum_source, "File_Name3"' in candidate.code
    assert "Table.Distinct(Table.SelectColumns" in candidate.code
    assert notebook.deployable
    assert 'require_transform("router")' in notebook.code
    assert 'route_aum_routes["STG_DATA"]' in notebook.code
    assert 'route_aum_routes["HFS_REJECTED_DATA"]' in notebook.code


def test_notebook_binds_unsupported_powercenter_operations() -> None:
    graph = EtlGraph(
        kind=GraphKind.MAPPING,
        nodes=(
            EtlNode(
                native_id="src",
                name="Accounts",
                operation="source",
                kind=NodeKind.SOURCE,
            ),
            EtlNode(
                native_id="lookup",
                name="Account Lookup",
                operation="lookup_procedure",
                kind=NodeKind.TRANSFORMATION,
            ),
            EtlNode(
                native_id="update",
                name="Apply Update Strategy",
                operation="update_strategy",
                kind=NodeKind.TRANSFORMATION,
            ),
            EtlNode(
                native_id="tgt",
                name="Curated Accounts",
                operation="target",
                kind=NodeKind.TARGET,
            ),
        ),
        edges=(
            EtlEdge(source="src", target="lookup"),
            EtlEdge(source="lookup", target="update"),
            EtlEdge(source="update", target="tgt"),
        ),
    )
    asset = EtlAsset(
        native_id="m_accounts",
        name="m_accounts",
        asset_type=AssetType.MAPPING,
        mapping_graphs=(graph,),
    )
    package = EtlPackage(
        source_platform=SourcePlatform.INFORMATICA_POWERCENTER,
        source_product="Informatica PowerCenter",
        export_id="repo",
        assets=(asset,),
    )

    dataflow = compile_asset(package, asset, "dataflow")
    notebook = compile_asset(package, asset, "notebook")

    assert not dataflow.deployable
    assert notebook.deployable
    assert 'account_lookup = require_transform("lookup")(accounts)' in notebook.code
    assert (
        'apply_update_strategy = require_transform("update")(account_lookup)'
        in notebook.code
    )
    assert "transform_bindings['lookup'] (lookup_procedure)" in (
        notebook.required_bindings
    )
    assert "transform_bindings['update'] (update_strategy)" in (
        notebook.required_bindings
    )


def test_notebook_router_binding_accepts_multiple_upstream_frames() -> None:
    graph = EtlGraph(
        kind=GraphKind.MAPPING,
        nodes=(
            EtlNode(
                native_id="left",
                name="Documents",
                operation="source",
                kind=NodeKind.SOURCE,
            ),
            EtlNode(
                native_id="right",
                name="Lookup Results",
                operation="source",
                kind=NodeKind.SOURCE,
            ),
            EtlNode(
                native_id="router",
                name="Route Documents",
                operation="router",
                kind=NodeKind.TRANSFORMATION,
                ports=(
                    EtlPort(name="DocumentId1", direction="output"),
                ),
                properties={
                    "router_groups": [
                        {
                            "name": "VALID",
                            "type": "OUTPUT",
                            "expression": "ISNULL(ERROR_DESC)",
                        },
                    ],
                    "port_groups": {"DocumentId1": "VALID"},
                },
            ),
            EtlNode(
                native_id="tgt",
                name="Valid Documents",
                operation="target",
                kind=NodeKind.TARGET,
            ),
        ),
        edges=(
            EtlEdge(source="left", target="router"),
            EtlEdge(source="right", target="router"),
            EtlEdge(
                source="router",
                target="tgt",
                source_port="DocumentId1",
            ),
        ),
    )
    asset = EtlAsset(
        native_id="m_documents",
        name="m_documents",
        asset_type=AssetType.MAPPING,
        mapping_graphs=(graph,),
    )
    package = EtlPackage(
        source_platform=SourcePlatform.INFORMATICA_POWERCENTER,
        source_product="Informatica PowerCenter",
        export_id="repo",
        assets=(asset,),
    )

    candidate = compile_asset(package, asset, "notebook")

    assert candidate.deployable
    assert (
        'route_documents_routes = require_transform("router")'
        "(documents, lookup_results)"
    ) in candidate.code
    assert 'route_documents_routes["VALID"]' in candidate.code


def test_sql_custom_transformation_compiles_as_explicit_binding() -> None:
    graph = EtlGraph(
        kind=GraphKind.MAPPING,
        nodes=(
            EtlNode(
                native_id="src",
                name="Footnotes",
                operation="source",
                kind=NodeKind.SOURCE,
            ),
            EtlNode(
                native_id="sql_sequence",
                name="Get Sequence",
                operation="custom_transformation",
                kind=NodeKind.TRANSFORMATION,
                properties={
                    "metadata_extensions": {
                        "SQL_Query": (
                            "SELECT hub_owner.sp_fn_get_sequence"
                            "('hub_owner.seq_footnotes_keystat')"
                        ),
                    },
                },
            ),
            EtlNode(
                native_id="tgt",
                name="Curated Footnotes",
                operation="target",
                kind=NodeKind.TARGET,
            ),
        ),
        edges=(
            EtlEdge(source="src", target="sql_sequence"),
            EtlEdge(source="sql_sequence", target="tgt"),
        ),
    )
    asset = EtlAsset(
        native_id="m_footnotes",
        name="m_footnotes",
        asset_type=AssetType.MAPPING,
        mapping_graphs=(graph,),
    )
    package = EtlPackage(
        source_platform=SourcePlatform.INFORMATICA_POWERCENTER,
        source_product="Informatica PowerCenter",
        export_id="repo",
        assets=(asset,),
    )

    candidate = compile_asset(package, asset, "dataflow")

    assert candidate.deployable
    assert "SqlTransformBindings" in candidate.code
    assert 'Record.Field(SqlTransformBindings, "sql_sequence")' in candidate.code
    assert "sql_transforms['sql_sequence']" in candidate.required_bindings


def test_powercenter_mapping_compiles_to_dataflow_and_notebook() -> None:
    source = FIXTURES / "powercenter" / "basic_repository.xml"
    adapter = PowerCenterSourceAdapter()
    match = adapter.probe(source, source.name)
    assert match is not None
    package = adapter.parse(source, match)
    workflow = next(asset for asset in package.assets if asset.name == "wf_orders")

    dataflow = compile_asset(package, workflow, "dataflow")
    notebook = compile_asset(package, workflow, "notebook")

    assert dataflow.deployable
    assert "Table.SelectRows" in dataflow.code
    assert "Record.Field(SourceBindings, \"Orders\")" in dataflow.code
    assert dataflow.loaded_outputs == ("orderscurated",)
    assert "destinations['orderscurated']" in dataflow.required_bindings
    assert notebook.deployable
    assert '.filter(F.col("Amount") > F.lit(0))' in notebook.code
    assert "display(orderscurated)" in notebook.code


def test_powercenter_single_session_does_not_compile_to_pipeline() -> None:
    source = FIXTURES / "powercenter" / "basic_repository.xml"
    adapter = PowerCenterSourceAdapter()
    match = adapter.probe(source, source.name)
    assert match is not None
    package = adapter.parse(source, match)
    workflow = next(asset for asset in package.assets if asset.name == "wf_orders")

    candidate = compile_asset(package, workflow, "pipeline")

    assert not candidate.deployable
    assert candidate.validation_state == "scaffold"
    assert candidate.diagnostics == (
        "A single PowerCenter session deploys directly as Dataflow Gen2; "
        "a Fabric Pipeline is not required",
    )


def test_powercenter_pipeline_is_blocked_when_mapping_is_not_deployable() -> None:
    source = FIXTURES / "powercenter" / "basic_repository.xml"
    adapter = PowerCenterSourceAdapter()
    match = adapter.probe(source, source.name)
    assert match is not None
    package = adapter.parse(source, match)
    workflow = next(asset for asset in package.assets if asset.name == "wf_orders")
    unsupported_graph = EtlGraph(
        kind=GraphKind.MAPPING,
        nodes=(
            EtlNode(
                native_id="src",
                name="Orders",
                operation="source",
                kind=NodeKind.SOURCE,
            ),
            EtlNode(
                native_id="lkp",
                name="Customer Lookup",
                operation="lookup_procedure",
                kind=NodeKind.TRANSFORMATION,
            ),
            EtlNode(
                native_id="tgt",
                name="Curated",
                operation="target",
                kind=NodeKind.TARGET,
            ),
        ),
        edges=(
            EtlEdge(source="src", target="lkp"),
            EtlEdge(source="lkp", target="tgt"),
        ),
    )
    workflow = workflow.model_copy(update={"mapping_graphs": (unsupported_graph,)})

    candidate = compile_asset(package, workflow, "pipeline")

    assert not candidate.deployable
    assert candidate.validation_state == "scaffold"
    assert "Pipeline dependency is not deployable" in candidate.diagnostics[0]


def test_idmc_mapping_and_taskflow_compile_to_fabric() -> None:
    source = FIXTURES / "idmc" / "basic_export"
    adapter = IdmcSourceAdapter()
    match = adapter.probe(source, "basic_export")
    assert match is not None
    package = adapter.parse(source, match)
    mapping = next(asset for asset in package.assets if asset.name == "m_orders")
    taskflow = next(asset for asset in package.assets if asset.name == "tf_orders")

    dataflow = compile_asset(package, mapping, "dataflow")
    pipeline = compile_asset(package, taskflow, "pipeline")

    assert dataflow.deployable
    assert "Table.SelectRows" in dataflow.code
    assert pipeline.deployable
    assert "Run mt_orders" in pipeline.code


def test_powercenter_multi_mapping_workflow_compiles_notebook_and_pipeline(
    tmp_path: Path,
) -> None:
    source = tmp_path / "multi_mapping.xml"
    source.write_text(
        """<?xml version="1.0"?>
<POWERMART REPOSITORY_VERSION="10.5">
  <REPOSITORY NAME="repo" VERSION="1">
    <FOLDER NAME="Trade">
      <SOURCE NAME="SharedCfg"/>
      <TARGET NAME="OutA"/>
      <TARGET NAME="OutB"/>
      <MAPPING NAME="m_step_one">
        <TRANSFORMATION NAME="SQ_Cfg" TYPE="Source Qualifier"/>
        <TRANSFORMATION NAME="Jnr_Cfg" TYPE="Joiner"/>
        <INSTANCE NAME="SharedCfg" TYPE="SOURCE"/>
        <INSTANCE NAME="SQ_Cfg" TYPE="TRANSFORMATION" TRANSFORMATION_NAME="SQ_Cfg"/>
        <INSTANCE NAME="Jnr_Cfg" TYPE="TRANSFORMATION" TRANSFORMATION_NAME="Jnr_Cfg"/>
        <INSTANCE NAME="OutA" TYPE="TARGET"/>
        <CONNECTOR FROMINSTANCE="SharedCfg" TOINSTANCE="SQ_Cfg"/>
        <CONNECTOR FROMINSTANCE="SQ_Cfg" TOINSTANCE="Jnr_Cfg"/>
        <CONNECTOR FROMINSTANCE="Jnr_Cfg" TOINSTANCE="OutA"/>
      </MAPPING>
      <MAPPING NAME="m_step_two">
        <TRANSFORMATION NAME="SQ_Cfg" TYPE="XML Source Qualifier"/>
        <TRANSFORMATION NAME="Mplt_Hdr" TYPE="Mapplet"/>
        <INSTANCE NAME="SharedCfg" TYPE="SOURCE"/>
        <INSTANCE NAME="SQ_Cfg" TYPE="TRANSFORMATION" TRANSFORMATION_NAME="SQ_Cfg"/>
        <INSTANCE NAME="Mplt_Hdr" TYPE="TRANSFORMATION" TRANSFORMATION_NAME="Mplt_Hdr"/>
        <INSTANCE NAME="OutB" TYPE="TARGET"/>
        <CONNECTOR FROMINSTANCE="SharedCfg" TOINSTANCE="SQ_Cfg"/>
        <CONNECTOR FROMINSTANCE="SQ_Cfg" TOINSTANCE="Mplt_Hdr"/>
        <CONNECTOR FROMINSTANCE="Mplt_Hdr" TOINSTANCE="OutB"/>
      </MAPPING>
      <WORKFLOW NAME="wf_multi">
        <TASK NAME="Start" TYPE="Start"/>
        <TASK NAME="Assign_Vars" TYPE="Assignment">
          <VALUEPAIR NAME="$$WF_DATE" VALUE="''"/>
        </TASK>
        <SESSION NAME="s_step_one" MAPPINGNAME="m_step_one"/>
        <SESSION NAME="s_step_two" MAPPINGNAME="m_step_two"/>
        <TASKINSTANCE NAME="Start" TASKNAME="Start" TASKTYPE="Start"/>
        <TASKINSTANCE NAME="Assign_Vars" TASKNAME="Assign_Vars" TASKTYPE="Assignment"/>
        <TASKINSTANCE NAME="s_step_one" TASKNAME="s_step_one" TASKTYPE="Session"/>
        <TASKINSTANCE NAME="s_step_two" TASKNAME="s_step_two" TASKTYPE="Session"/>
        <WORKFLOWLINK FROMTASK="Start" TOTASK="Assign_Vars"/>
        <WORKFLOWLINK FROMTASK="Assign_Vars" TOTASK="s_step_one"/>
        <WORKFLOWLINK FROMTASK="s_step_one" TOTASK="s_step_two"/>
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
    workflow = package.assets[0]
    initial = assess_package(package)[0]

    compiled = compile_asset_targets(package, workflow)
    routed = apply_native_route(package, workflow, initial)
    dataflow = compiled.dataflow
    notebook = compiled.notebook
    pipeline = compiled.pipeline

    assert routed.recommended_target == "Mixed Fabric solution"
    assert routed.target_components == ("Fabric Notebook", "Fabric Pipeline")
    assert routed.migration_wave != "Redesign"
    assert "xml_source_qualifier" not in routed.unsupported_components
    assert "assignment" not in routed.unsupported_components
    assert not dataflow.deployable
    assert "m_step_one: Unsupported operations: joiner" in dataflow.diagnostics[0]

    assert notebook.deployable
    ast.parse(notebook.code)
    assert "def _read_source(location):" in notebook.code
    assert "s_step_one_sharedcfg = _read_source(" in notebook.code
    assert "s_step_two_sharedcfg = _read_source(" in notebook.code
    assert "m_step_one/SharedCfg" in notebook.code
    assert "m_step_two/SharedCfg" in notebook.code
    assert "WF_DATE = globals().get('WF_DATE'" in notebook.code
    assert "workflow_vars.setdefault('$$WF_DATE', WF_DATE)" in notebook.code

    assert pipeline.deployable
    payload = json.loads(pipeline.code)
    activities = payload["properties"]["activities"]
    assert [item["type"] for item in activities] == [
        "SetVariable",
        "TridentNotebook",
    ]
    assert activities[0]["typeProperties"] == {"variableName": "WF_DATE", "value": ""}
    assert activities[1]["name"] == "Run_wf_multi"
    assert activities[1]["dependsOn"][0]["activity"] == "Assign_Vars"
    assert activities[1]["typeProperties"]["parameters"] == {
        "WF_DATE": {"type": "string", "value": "@variables('WF_DATE')"},
    }


