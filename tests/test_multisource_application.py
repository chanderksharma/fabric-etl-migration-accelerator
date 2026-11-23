"""Mixed-source discovery and assessment contracts."""

import io
import json
import shutil
import sys
import types
import zipfile
from pathlib import Path

import pytest

from accelerator.runtime.runs import RunService
from accelerator.server import api
from etl_migration_core.intake.discovery import DiscoveryService
from etl_target_fabric.application import FabricAssessmentApplication as AssessmentApplication

FIXTURES = Path(__file__).parent / "fixtures"


def _idmc_archive(destination: Path) -> None:
    root = FIXTURES / "idmc" / "basic_export"
    with zipfile.ZipFile(destination, "w", compression=zipfile.ZIP_DEFLATED) as archive:
        for path in root.rglob("*"):
            if path.is_file():
                archive.write(path, path.relative_to(root).as_posix())


def _powercenter_archive(destination: Path) -> None:
    source = FIXTURES / "powercenter" / "basic_repository.xml"
    with zipfile.ZipFile(destination, "w", compression=zipfile.ZIP_DEFLATED) as archive:
        archive.write(source, "exports/basic_repository.xml")


def test_discovery_recognizes_powercenter_and_idmc_packages(tmp_path: Path) -> None:
    powercenter = tmp_path / "repository.xml"
    shutil.copyfile(FIXTURES / "powercenter" / "basic_repository.xml", powercenter)
    idmc = tmp_path / "idmc-export.zip"
    _idmc_archive(idmc)

    summary = DiscoveryService().discover(tmp_path)

    assert summary.workflow_count == 2
    by_name = {item.display_path: item for item in summary.workflows}
    assert by_name["repository.xml"].source_platform == "informatica_powercenter"
    assert by_name["idmc-export.zip"].source_platform == "informatica_idmc"
    assert not any(item.path.endswith("manifest.json") for item in summary.skipped)


def test_powercenter_xml_inside_zip_keeps_adapter_metadata(tmp_path: Path) -> None:
    archive = tmp_path / "powercenter.zip"
    _powercenter_archive(archive)

    preview = DiscoveryService().discover(archive)
    result = AssessmentApplication().assess(archive)

    assert preview.workflow_count == 1
    assert preview.workflows[0].source_platform == "informatica_powercenter"
    assert preview.workflows[0].adapter_id == "informatica-powercenter"
    assert result.failed_count == 0
    assert any(item.path.endswith("wf_orders") for item in result.assessments)


def test_application_assesses_mixed_alteryx_and_informatica_estate(
    tmp_path: Path,
) -> None:
    shutil.copyfile(
        Path(__file__).parents[1] / "alteryx-workflows" / "01_low_clean_orders.yxmd",
        tmp_path / "orders.yxmd",
    )
    shutil.copyfile(
        FIXTURES / "powercenter" / "basic_repository.xml",
        tmp_path / "repository.xml",
    )
    _idmc_archive(tmp_path / "idmc-export.zip")

    result = AssessmentApplication().assess(tmp_path)

    assert result.failed_count == 0
    assert result.workflow_count == 5
    assert {item.source_platform for item in result.assessments} == {
        "alteryx",
        "informatica_powercenter",
        "informatica_idmc",
    }
    assert any(item.path.endswith("wf_orders") for item in result.assessments)
    assert any(item.path.endswith("m_orders") for item in result.assessments)
    assert any(item.path.endswith("tf_orders") for item in result.assessments)


def test_run_service_assesses_one_package_into_multiple_assets(tmp_path: Path) -> None:
    source = tmp_path / "idmc-export.zip"
    _idmc_archive(source)
    service = RunService(tmp_path / "state")

    run = service.create_run(service.preview(source).snapshot_id)
    service.execute(run.id)
    completed = service.get_run(run.id)

    assert completed.status == "completed"
    assert completed.result is not None
    assert completed.result.workflow_count == 3
    assert {item.source_platform for item in completed.result.assessments} == {
        "informatica_idmc"
    }


def test_run_service_snapshots_extracted_idmc_and_detects_changes(tmp_path: Path) -> None:
    source = tmp_path / "export"
    shutil.copytree(FIXTURES / "idmc" / "basic_export", source)
    with RunService(tmp_path / "state") as service:
        preview = service.preview(source)
        snapshot = Path(preview.workflows[0].source_path)
        assert snapshot.is_dir()
        assert service.preview(source).snapshot_id == preview.snapshot_id

        run = service.create_run(preview.snapshot_id)
        service.execute(run.id)
        completed = service.get_run(run.id)
        assert completed.status == "completed"
        assert completed.result is not None
        assert completed.result.workflow_count == 3
        assert len(service.evidence(run.id).workflows) == 3

        (snapshot / "manifest.json").write_text("{}", encoding="utf-8")
        with pytest.raises(ValueError, match="snapshot changed"):
            service.create_run(preview.snapshot_id)


def test_fabric_notebook_assesses_and_exports_web_app_targets(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    root = Path(__file__).parents[1]
    source = tmp_path / "input"
    source.mkdir()
    shutil.copyfile(
        root / "alteryx-workflows" / "sample_merge_append_joins.yxmd",
        source / "=orders.yxmd",
    )
    shutil.copyfile(FIXTURES / "powercenter" / "basic_repository.xml", source / "repository.xml")
    _idmc_archive(source / "idmc-export.zip")
    service = RunService(tmp_path / "web-state")
    run = service.create_run(service.preview(source).snapshot_id)
    service.execute(run.id)
    static_result = service.get_run(run.id).result
    assert static_result is not None
    baseline = AssessmentApplication().assess(source)
    assert {item.path: item.model_dump() for item in baseline.assessments} == {
        item.path: item.model_dump() for item in static_result.assessments
    }, "portfolio assessment equals the static facade; neither runs a compiler"
    alteryx_baseline = next(item for item in baseline.assessments if item.path == "=orders.yxmd")
    assert alteryx_baseline.recommended_target == "Dataflow Gen2"

    notebook = json.loads(
        (root / "notebooks" / "fabric-portfolio-assessment.ipynb").read_text(encoding="utf-8")
    )
    code_cells = [cell for cell in notebook["cells"] if cell["cell_type"] == "code"]
    params_cell = next(cell for cell in code_cells if cell["id"] == "parameters")
    assert params_cell["metadata"].get("tags") == ["parameters"]
    cells = {
        cell["id"]: compile("".join(cell["source"]), f"notebook:{cell['id']}", "exec")
        for cell in code_cells
    }

    saved_tables: dict[str, list[dict[str, object]]] = {}
    sql_queries: list[str] = []

    class FakeWriter:
        def __init__(self, rows: list[dict[str, object]]) -> None:
            self._rows = rows

        def format(self, _name: str) -> "FakeWriter":
            return self

        def mode(self, _name: str) -> "FakeWriter":
            return self

        def saveAsTable(self, table_name: str) -> None:
            saved_tables.setdefault(table_name, []).extend(self._rows)

    class FakeDataFrame(list[dict[str, object]]):
        @property
        def write(self) -> FakeWriter:
            return FakeWriter(list(self))

        def createOrReplaceTempView(self, _name: str) -> None:
            return None

    class FakeTable:
        def __init__(self, columns: list[str]) -> None:
            self.columns = columns

    class FakeCatalog:
        @staticmethod
        def tableExists(_table_name: str) -> bool:
            return False

    class SparkDisplayStub:
        catalog = FakeCatalog()

        def createDataFrame(
            self, rows: list[dict[str, object]], _schema: object = None
        ) -> FakeDataFrame:
            return FakeDataFrame(rows)

        def sql(self, query: str) -> None:
            sql_queries.append(query)

        def table(self, table_name: str) -> FakeTable:
            rows = saved_tables.get(table_name, [])
            return FakeTable(list(rows[0]) if rows else [])

    pyspark_mod = types.ModuleType("pyspark")
    pyspark_sql = types.ModuleType("pyspark.sql")
    pyspark_types = types.ModuleType("pyspark.sql.types")
    for type_name in (
        "BooleanType",
        "DoubleType",
        "IntegerType",
        "StringType",
        "StructField",
        "StructType",
        "TimestampType",
    ):
        setattr(pyspark_types, type_name, lambda *args, **kwargs: (args, kwargs))
    monkeypatch.setitem(sys.modules, "pyspark", pyspark_mod)
    monkeypatch.setitem(sys.modules, "pyspark.sql", pyspark_sql)
    monkeypatch.setitem(sys.modules, "pyspark.sql.types", pyspark_types)

    displayed: list[list[dict[str, object]]] = []
    dashboards: list[str] = []
    scope: dict[str, object] = {
        "spark": SparkDisplayStub(),
        "display": displayed.append,
        "displayHTML": dashboards.append,
    }
    exec(cells["parameters"], scope)
    scope.update(LAKEHOUSE_FILES=tmp_path, INPUT_PATH="input", REPORT_FOLDER="reports")
    exec(cells["preview"], scope)
    with pytest.raises(RuntimeError, match="CONFIRM_ASSESSMENT"):
        exec(cells["assess"], scope)
    scope.update(
        CONFIRM_ASSESSMENT=True,
        PERSIST_DELTA_TABLES=True,
    )
    for cell in code_cells:
        if cell["id"] in {"parameters", "preview"}:
            continue
        exec(cells[cell["id"]], scope)
    assert set(saved_tables) == {
        "etl_assessment_run",
        "etl_workflow_assessment",
        "etl_tool_inventory",
        "etl_finding",
        "etl_dependency",
        "etl_workflow_node",
        "etl_workflow_connection",
        "etl_capacity_profile",
    }
    assert len(saved_tables["etl_workflow_assessment"]) == 5
    assert len(saved_tables["etl_capacity_profile"]) == 5
    assert all(
        isinstance(row["ComplexityUnits"], (int, float))
        and row["ComplexityUnits"] >= 0
        and isinstance(row["TotalSteps"], int)
        and row["TotalSteps"] >= 0
        for row in saved_tables["etl_capacity_profile"]
    )
    assert any(
        isinstance(row["TotalSteps"], int) and row["TotalSteps"] > 0
        for row in saved_tables["etl_capacity_profile"]
    )
    assert any("UPDATE etl_assessment_run SET IsLatestCompletedRun" in q for q in sql_queries)
    assert not (tmp_path / "reports").exists()
    scope["WRITE_REPORTS"] = True
    exec(cells["export"], scope)

    [report_path] = (tmp_path / "reports").glob("*/assessment.json")
    report = json.loads(report_path.read_text(encoding="utf-8"))
    assert report["workflow_count"] == 5
    assert report["failed_count"] == 0
    assert {row["source_platform"] for row in report["assessments"]} == {
        "alteryx", "informatica_powercenter", "informatica_idmc"
    }
    assert dashboards == []
    expected = {
        item.path: (item.recommended_target, item.migration_wave, item.complexity_score)
        for item in baseline.assessments
    }
    assert expected["=orders.yxmd"][0] == "Dataflow Gen2"
    assert {
        row["path"]: (row["recommended_target"], row["migration_wave"], row["complexity_score"])
        for row in report["assessments"]
    } == expected
    assert report["workflows"] == [
        item.model_dump(mode="json", include={"display_path", "sha256"})
        for item in baseline.workflows
    ]
    assert report["routing_basis"] == "static_mapping"
    assert all("estimated_effort_days" in row for row in report["assessments"])
    csv_report = report_path.with_suffix(".csv").read_text(encoding="utf-8-sig")
    assert "'=orders.yxmd" in csv_report
    assert "estimated_effort_days" in csv_report


def test_run_service_generates_platform_scoped_informatica_artifacts(
    tmp_path: Path,
) -> None:
    source = tmp_path / "repository.xml"
    shutil.copyfile(FIXTURES / "powercenter" / "basic_repository.xml", source)
    service = RunService(tmp_path / "state", artifact_root=tmp_path / "artifacts")
    run = service.create_run(service.preview(source).snapshot_id)
    service.execute(run.id)

    result = service.write_artifacts(run.id, "dataflow")

    candidate = next(item for item in result.candidates if item.workflow.endswith("wf_orders"))
    assert candidate.source_platform == "informatica_powercenter"
    assert candidate.deployable
    folder = (
        result.root
        / "informatica-powercenter"
        / "wf_orders"
    )
    assert (folder / "dataflow-mashup.pq").is_file()
    assert candidate.artifact_path == "informatica-powercenter/wf_orders"


def test_powercenter_evidence_includes_mapping_and_orchestration_graphs(
    tmp_path: Path,
) -> None:
    source = tmp_path / "repository.xml"
    shutil.copyfile(FIXTURES / "powercenter" / "basic_repository.xml", source)
    service = RunService(tmp_path / "state")
    run = service.create_run(service.preview(source).snapshot_id)
    service.execute(run.id)

    evidence = service.evidence(run.id, 0)

    workflow = next(
        item for item in evidence.workflows if item.workflow_path.endswith("wf_orders")
    )
    assert {node.name for node in workflow.nodes} == {
        "Orders",
        "SQ_Orders",
        "FLT_Valid",
        "OrdersCurated",
        "Start",
        "s_orders",
    }
    assert workflow.node_count == 6
    assert workflow.edge_count == 4


def test_powercenter_workflow_plans_dataflow_without_pipeline(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    source = tmp_path / "repository.xml"
    shutil.copyfile(FIXTURES / "powercenter" / "basic_repository.xml", source)
    service = RunService(tmp_path / "state", artifact_root=tmp_path / "artifacts")
    run = service.create_run(service.preview(source).snapshot_id)
    service.execute(run.id)

    service.write_artifacts(run.id, "dataflow")
    result = service.write_artifacts(run.id, "pipeline")

    plan = json.loads((result.root / "deployment-plan.json").read_text(encoding="utf-8"))
    workflow = next(
        item for item in plan["workflows"] if item["workflow"].endswith("wf_orders")
    )
    assert workflow["status"] == "native_ready"
    assert [item["type"] for item in workflow["selected_components"]] == ["Dataflow"]
    folder = result.root / workflow["artifact_path"]
    assert not (folder / "deployment-bundle.json").exists()
    assert not (folder / "pipeline-create-item.json").exists()
    monkeypatch.setattr(api.app.state, "run_service", service, raising=False)
    _, selected_target, artifact_path = api._resolve_deployment_artifact(
        run.id,
        next(
            item.workflow
            for item in result.candidates
            if item.workflow.endswith("wf_orders")
        ),
        "dataflow",
    )
    assert selected_target == "dataflow"
    assert artifact_path == workflow["artifact_path"]


def test_run_service_generates_platform_scoped_idmc_pipeline_artifacts(
    tmp_path: Path,
) -> None:
    source = tmp_path / "idmc-export.zip"
    _idmc_archive(source)
    service = RunService(tmp_path / "state", artifact_root=tmp_path / "artifacts")
    run = service.create_run(service.preview(source).snapshot_id)
    service.execute(run.id)

    result = service.write_artifacts(run.id, "pipeline")

    candidate = next(item for item in result.candidates if item.workflow.endswith("tf_orders"))
    assert candidate.source_platform == "informatica_idmc"
    assert candidate.deployable
    assert candidate.artifact_path is not None
    folder = result.root / candidate.artifact_path
    assert "pipeline-content.json" in candidate.definition_files
    assert (folder / "pipeline-content.json").is_file()
    assert (folder / "pipeline.platform.json").is_file()
    assert (folder / "pipeline-create-item.json").is_file()
    manifest = json.loads(
        (folder / "pipeline-manifest.json").read_text(encoding="utf-8")
    )
    assert manifest["source_platform"] == "informatica_idmc"
    assert manifest["source_product"] == "Informatica IDMC"
    assert manifest["asset_type"] == "taskflow"
    plan = json.loads((result.root / "deployment-plan.json").read_text(encoding="utf-8"))
    taskflow_plan = next(
        item for item in plan["workflows"] if item["workflow"].endswith("tf_orders")
    )
    assert taskflow_plan["status"] == "native_ready"
    assert [item["type"] for item in taskflow_plan["selected_components"]] == [
        "DataPipeline"
    ]


def test_run_service_exposes_source_neutral_idmc_graph_evidence(
    tmp_path: Path,
) -> None:
    source = tmp_path / "idmc-export.zip"
    _idmc_archive(source)
    service = RunService(tmp_path / "state")
    run = service.create_run(service.preview(source).snapshot_id)
    service.execute(run.id)

    evidence = service.evidence(run.id, 0)

    assert {item.workflow_path.rsplit("!", 1)[-1] for item in evidence.workflows} == {
        "Sales/m_orders",
        "Sales/mt_orders",
        "Sales/tf_orders",
    }
    taskflow = next(
        item for item in evidence.workflows if item.workflow_path.endswith("tf_orders")
    )
    assert taskflow.parse_status == "parsed"
    assert taskflow.nodes
    assert taskflow.edges


def test_writing_one_source_run_preserves_other_run_artifacts(tmp_path: Path) -> None:
    powercenter = tmp_path / "repository.xml"
    shutil.copyfile(FIXTURES / "powercenter" / "basic_repository.xml", powercenter)
    idmc = tmp_path / "idmc-export.zip"
    _idmc_archive(idmc)
    service = RunService(tmp_path / "state", artifact_root=tmp_path / "artifacts")

    first = service.create_run(service.preview(powercenter).snapshot_id)
    service.execute(first.id)
    first_result = service.write_artifacts(first.id, "dataflow")
    first_candidate = next(
        item for item in first_result.candidates if item.workflow.endswith("wf_orders")
    )
    assert first_candidate.artifact_path is not None
    first_manifest = (
        first_result.root
        / first_candidate.artifact_path
        / "dataflow-manifest.json"
    )
    assert first_manifest.is_file()

    second = service.create_run(service.preview(idmc).snapshot_id)
    service.execute(second.id)
    service.write_artifacts(second.id, "dataflow")

    assert first_manifest.is_file()


def test_multi_mapping_powercenter_workflow_writes_bundle_and_zip(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    source = tmp_path / "multi.xml"
    source.write_text(
        """<?xml version="1.0"?>
<POWERMART REPOSITORY_VERSION="10.5">
  <REPOSITORY NAME="repo" VERSION="1">
    <FOLDER NAME="Trade">
      <SOURCE NAME="SrcA"/>
      <SOURCE NAME="SrcB"/>
      <TARGET NAME="TgtA"/>
      <TARGET NAME="TgtB"/>
      <MAPPING NAME="m_a">
        <TRANSFORMATION NAME="SQ_A" TYPE="Source Qualifier"/>
        <TRANSFORMATION NAME="Jnr_A" TYPE="Joiner"/>
        <INSTANCE NAME="SrcA" TYPE="SOURCE"/>
        <INSTANCE NAME="SQ_A" TYPE="TRANSFORMATION" TRANSFORMATION_NAME="SQ_A"/>
        <INSTANCE NAME="Jnr_A" TYPE="TRANSFORMATION" TRANSFORMATION_NAME="Jnr_A"/>
        <INSTANCE NAME="TgtA" TYPE="TARGET"/>
        <CONNECTOR FROMINSTANCE="SrcA" TOINSTANCE="SQ_A"/>
        <CONNECTOR FROMINSTANCE="SQ_A" TOINSTANCE="Jnr_A"/>
        <CONNECTOR FROMINSTANCE="Jnr_A" TOINSTANCE="TgtA"/>
      </MAPPING>
      <MAPPING NAME="m_b">
        <TRANSFORMATION NAME="SQ_B" TYPE="Source Qualifier"/>
        <INSTANCE NAME="SrcB" TYPE="SOURCE"/>
        <INSTANCE NAME="SQ_B" TYPE="TRANSFORMATION" TRANSFORMATION_NAME="SQ_B"/>
        <INSTANCE NAME="TgtB" TYPE="TARGET"/>
        <CONNECTOR FROMINSTANCE="SrcB" TOINSTANCE="SQ_B"/>
        <CONNECTOR FROMINSTANCE="SQ_B" TOINSTANCE="TgtB"/>
      </MAPPING>
      <WORKFLOW NAME="wf_multi">
        <TASK NAME="Start" TYPE="Start"/>
        <TASK NAME="Assign_Vars" TYPE="Assignment">
          <VALUEPAIR NAME="$$WF_FLAG" VALUE="'1'"/>
        </TASK>
        <SESSION NAME="s_a" MAPPINGNAME="m_a"/>
        <SESSION NAME="s_b" MAPPINGNAME="m_b"/>
        <TASKINSTANCE NAME="Start" TASKNAME="Start" TASKTYPE="Start"/>
        <TASKINSTANCE NAME="Assign_Vars" TASKNAME="Assign_Vars" TASKTYPE="Assignment"/>
        <TASKINSTANCE NAME="s_a" TASKNAME="s_a" TASKTYPE="Session"/>
        <TASKINSTANCE NAME="s_b" TASKNAME="s_b" TASKTYPE="Session"/>
        <WORKFLOWLINK FROMTASK="Start" TOTASK="Assign_Vars"/>
        <WORKFLOWLINK FROMTASK="Assign_Vars" TOTASK="s_a"/>
        <WORKFLOWLINK FROMTASK="s_a" TOTASK="s_b"/>
      </WORKFLOW>
    </FOLDER>
  </REPOSITORY>
</POWERMART>
""",
        encoding="utf-8",
    )
    service = RunService(tmp_path / "state", artifact_root=tmp_path / "artifacts")
    run = service.create_run(service.preview(source).snapshot_id)
    service.execute(run.id)

    completed = service.get_run(run.id)
    assert completed.result is not None
    assert completed.routing_basis == "static_mapping"
    assert completed.result.assessments[0].target_components == [
        "Dataflow Gen2",
        "Fabric Pipeline",
    ]

    confirmed = service.ensure_fabric_fit(run.id)
    assert confirmed.result is not None
    assessment = confirmed.result.assessments[0]
    assert assessment.recommended_target == "Mixed Fabric solution"
    assert assessment.target_components == ["Fabric Notebook", "Fabric Pipeline"]
    assert assessment.dependencies == ["m_a", "m_b"]
    assert assessment.data_sources == ["SrcA", "TgtA", "SrcB", "TgtB"]

    evidence = service.evidence(run.id, 0)
    assert len(evidence.workflows) == 1
    support_by_node = {node.name: node.support for node in evidence.workflows[0].nodes}
    assert support_by_node["Start"] == "neutral"
    assert support_by_node["Assign_Vars"] == "pipeline"
    assert support_by_node["s_a"] == "pipeline"
    assert support_by_node["SQ_A"] == "dataflow"

    bundle_bytes, bundle_name = service.workflow_package(run.id, assessment.path)
    assert bundle_name == "wf_multi-fabric-bundle.zip"
    assert bundle_bytes == service.workflow_package(run.id, assessment.path)[0]
    with zipfile.ZipFile(io.BytesIO(bundle_bytes)) as archive:
        names = set(archive.namelist())
        assert {
            "notebook-create-item.json",
            "notebook-content.ipynb",
            "pipeline-create-item.json",
            "pipeline-content.json",
            "deployment-bundle.json",
            "README.md",
        }.issubset(names)
        bundle_meta = json.loads(archive.read("deployment-bundle.json"))
        assert bundle_meta["deploymentOrder"] == ["Notebook", "DataPipeline"]
        readme = archive.read("README.md").decode("utf-8")
        assert "{{NOTEBOOK_ITEM_ID}}" in readme
        assert "{{DATAFLOW_ITEM_ID}}" not in readme
        notebook_json = json.loads(archive.read("notebook-content.ipynb"))
        code_cells = [
            cell for cell in notebook_json["cells"] if cell["cell_type"] == "code"
        ]
        assert any(
            "parameters" in cell["metadata"].get("tags", []) for cell in code_cells
        )
        assert max(len(cell["source"]) for cell in code_cells) <= 16
        assert "Informatica PowerCenter" in "".join(
            "".join(cell["source"])
            for cell in notebook_json["cells"]
            if cell["cell_type"] == "markdown"
        )

    monkeypatch.setattr(api.app.state, "run_service", service, raising=False)
    _, selected_target, artifact_path = api._resolve_deployment_artifact(
        run.id, assessment.path, "bundle"
    )
    assert selected_target == "bundle"
    assert artifact_path == "informatica-powercenter/wf_multi"


