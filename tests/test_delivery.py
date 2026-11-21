"""End-to-end contracts for the local delivery slice."""

import ast
import base64
import io
import json
import sqlite3
import time
import zipfile
from collections.abc import Iterator
from concurrent.futures import Future, wait
from contextlib import closing
from pathlib import Path
from threading import Event, Thread
from typing import IO

import pytest
from fastapi.testclient import TestClient
from typer.testing import CliRunner

from accelerator.cli.app import app as cli
from accelerator.runtime.runs import RunService
from accelerator.server.api import app
from etl_migration_core.intake.discovery import DiscoveryService, InputRejectedError
from etl_migration_core.intake.domain import DiscoveryLimits
from etl_target_fabric.assessment.portfolio import (
    FabricAssessmentApplication as AssessmentApplication,
)
from etl_target_fabric.assessment.schemas import (
    WorkflowAssessmentResponse,
    WorkflowCandidateResponse,
)
from etl_target_fabric.assessment.workflow import WorkflowParseError, assess_workflow

WORKFLOW = b"""<AlteryxDocument><Nodes>
<Node ToolID="1"><GuiSettings Plugin="AlteryxBasePluginsGui.InputData.InputData"/>
<Properties><Configuration><File>orders.csv</File></Configuration></Properties></Node>
<Node ToolID="2"><GuiSettings Plugin="AlteryxBasePluginsGui.Filter.Filter"/>
<Properties><Configuration><Expression>[Amount] &gt; 0</Expression>
</Configuration></Properties></Node></Nodes><Connections><Connection>
<Origin ToolID="1" Connection="Output"/><Destination ToolID="2" Connection="Input"/>
</Connection></Connections></AlteryxDocument>"""


def archive_bytes(members: dict[str, bytes]) -> bytes:
    stream = io.BytesIO()
    with zipfile.ZipFile(stream, "w") as archive:
        for name, content in members.items():
            archive.writestr(name, content)
    return stream.getvalue()


@pytest.mark.parametrize("extension", [".zip", ".yxzp"])
def test_archive_assessment_reads_members(tmp_path: Path, extension: str) -> None:
    path = tmp_path / f"estate{extension}"
    path.write_bytes(archive_bytes({"nested/orders.yxmd": WORKFLOW}))
    result = AssessmentApplication().assess(path)
    assert result.workflow_count == 1
    assert result.failed_count == 0
    assert result.assessments[0].path == "nested/orders.yxmd"


def test_nested_package_and_bad_workflow_are_isolated(tmp_path: Path) -> None:
    path = tmp_path / "estate.zip"
    path.write_bytes(
        archive_bytes(
            {
                "bundle.yxzp": archive_bytes({"orders.yxmd": WORKFLOW}),
                "bad.yxmd": b"<broken",
            }
        )
    )
    result = AssessmentApplication().assess(path)
    assert result.workflow_count == 1
    assert result.failed_count == 1
    assert "bundle.yxzp" in result.assessments[0].path


def test_custom_plugin_is_not_classified_by_suffix(tmp_path: Path) -> None:
    path = tmp_path / "custom.yxmd"
    path.write_bytes(
        WORKFLOW.replace(b"AlteryxBasePluginsGui.Filter.Filter", b"Company.Filter.Filter")
    )
    result = assess_workflow(path)
    assert "Filter" in result.unsupported_tools


@pytest.mark.parametrize(
    "content",
    [
        b"<Workflow/>",
        b'<!DOCTYPE a [<!ENTITY secret "x">]><AlteryxDocument>&secret;</AlteryxDocument>',
    ],
)
def test_wrong_root_and_entities_are_typed_parse_failures(tmp_path: Path, content: bytes) -> None:
    path = tmp_path / "bad.yxmd"
    path.write_bytes(content)
    with pytest.raises(WorkflowParseError):
        assess_workflow(path)


@pytest.mark.parametrize("member", ["CON.yxmd", "file:stream.yxmd", "folder./x.yxmd"])
def test_windows_unsafe_archive_names_are_rejected(tmp_path: Path, member: str) -> None:
    path = tmp_path / "unsafe.zip"
    path.write_bytes(archive_bytes({member: WORKFLOW}))
    with pytest.raises(InputRejectedError):
        DiscoveryService().discover(path)


def test_case_colliding_archive_members_are_rejected(tmp_path: Path) -> None:
    path = tmp_path / "unsafe.zip"
    path.write_bytes(archive_bytes({"A.yxmd": WORKFLOW, "a.yxmd": WORKFLOW}))
    with pytest.raises(InputRejectedError):
        DiscoveryService().discover(path)


def test_cli_assess_returns_actual_assessments(tmp_path: Path) -> None:
    path = tmp_path / "orders.yxmd"
    path.write_bytes(WORKFLOW)
    result = CliRunner().invoke(cli, ["assess", str(path)])
    assert result.exit_code == 0
    assert json.loads(result.stdout)["assessments"][0]["tool_count"] == 2


def test_zip_upload_can_be_confirmed() -> None:
    response = TestClient(app, base_url="http://localhost").post(
        "/api/assessment/upload",
        data={"mode": "zip"},
        files=[
            ("files", ("estate.zip", archive_bytes({"orders.yxmd": WORKFLOW}), "application/zip"))
        ],
    )
    assert response.status_code == 200
    assert response.json()["workflow_count"] == 1


def test_candidate_generation_produces_deployable_definition(tmp_path: Path) -> None:
    from etl_target_fabric.compilers.alteryx import generate_candidate

    path = tmp_path / "orders.yxmd"
    path.write_bytes(WORKFLOW)
    for target in ("notebook", "dataflow"):
        candidate = generate_candidate(path, target)
        assert candidate.validation_state == "generated_unvalidated"
        assert candidate.deployable
        assert candidate.definition_ready
        assert candidate.source_sha256
        if target == "notebook":
            ast.parse(candidate.code)
            assert "Source binding and semantic validation are required" not in candidate.code


def test_generation_scaffolds_unknown_semantics(tmp_path: Path) -> None:
    from etl_target_fabric.compilers.alteryx import generate_candidate

    path = tmp_path / "custom.yxmd"
    path.write_bytes(
        WORKFLOW.replace(b"AlteryxBasePluginsGui.Filter.Filter", b"Company.Filter.Filter")
    )
    candidate = generate_candidate(path, "notebook")
    assert candidate.validation_state == "scaffold"
    assert candidate.translation_mode == "scaffold"
    assert not candidate.deployable
    assert not candidate.definition_ready
    assert not candidate.runtime_ready
    assert candidate.diagnostics
    ast.parse(candidate.code)
    assert "Migration scaffold requires implementation" in candidate.code


def test_union_crosstab_graph_compiles_natively() -> None:
    from etl_target_fabric.compilers.alteryx import generate_candidate

    source = Path(__file__).parents[1] / "alteryx-workflows" / "06_high_channel_crosstab.yxmd"
    notebook = generate_candidate(source, "notebook")
    assert notebook.runtime_ready
    assert not notebook.diagnostics
    assert "unionByName" in notebook.code
    assert '.pivot("Channel")' in notebook.code
    ast.parse(notebook.code)

    dataflow = generate_candidate(source, "dataflow")
    assert dataflow.definition_ready
    assert not dataflow.runtime_ready
    assert not dataflow.diagnostics
    assert "Table.Combine" in dataflow.code
    assert "Table.Pivot" in dataflow.code
    assert "destinations['channel_crosstab']" in dataflow.required_bindings


def test_reconciliation_compiles_to_multi_query_dataflow() -> None:
    from etl_target_fabric.compilers.alteryx import generate_candidate

    source = (
        Path(__file__).parents[1]
        / "alteryx-workflows"
        / "11_multi_container_reconciliation.yxmd"
    )
    assessment = assess_workflow(source)
    candidate = generate_candidate(source, "dataflow")

    assert "ToolContainer" not in assessment.unsupported_tools
    assert candidate.definition_ready
    assert candidate.translation_mode == "native"
    assert candidate.diagnostics == []
    assert not candidate.runtime_ready
    assert candidate.code.startswith("section Section1;")
    assert "Table.NestedJoin" in candidate.code
    assert "Table.ExpandTableColumn" in candidate.code
    assert "Table.Combine" in candidate.code
    assert "MigrationGraph" not in candidate.code
    assert candidate.code.count("shared ") == len(candidate.definition_queries) == 30
    assert [group.name for group in candidate.query_groups] == [
        "00 Source Files",
        "01 Ledger Alpha and Beta",
        "02 Reference Enrichment",
        "03 Settlement Reconciliation",
        "04 Final Outputs",
        "05 Destinations",
    ]
    assert len(candidate.query_group_assignments) == 29
    assert set(candidate.query_group_assignments).issubset(candidate.definition_queries)
    assert set(candidate.loaded_queries) == {
        "file_settlement_export",
        "load_settlement",
        "file_alpha_beta_export",
        "load_alpha_beta",
    }
    assert set(candidate.loaded_queries).issubset(candidate.definition_queries)
    assert len(candidate.required_bindings) == 14


def test_dataflow_query_groups_preserve_nested_alteryx_containers(tmp_path: Path) -> None:
    from etl_target_fabric.compilers.alteryx import generate_candidate

    source = tmp_path / "nested-containers.yxmd"
    source.write_text(
        """<AlteryxDocument><Nodes>
<Node ToolID="100">
  <GuiSettings Plugin="AlteryxGuiToolkit.ToolContainer.ToolContainer">
    <Position x="0" y="0" width="500" height="500"/>
  </GuiSettings>
  <Properties><Configuration><Caption>Outer</Caption></Configuration></Properties>
</Node>
<Node ToolID="101">
  <GuiSettings Plugin="AlteryxGuiToolkit.ToolContainer.ToolContainer">
    <Position x="50" y="50" width="200" height="200"/>
  </GuiSettings>
  <Properties><Configuration><Caption>Inner</Caption></Configuration></Properties>
</Node>
<Node ToolID="1">
  <GuiSettings Plugin="AlteryxBasePluginsGui.DbFileInput.DbFileInput">
    <Position x="100" y="100"/>
  </GuiSettings>
  <Properties><Configuration><File>orders.csv</File></Configuration></Properties>
</Node>
<Node ToolID="2">
  <GuiSettings Plugin="AlteryxBasePluginsGui.OutputData.OutputData">
    <Position x="400" y="400"/>
  </GuiSettings>
  <Properties><Configuration><File>orders-out.csv</File></Configuration></Properties>
</Node>
</Nodes><Connections><Connection>
  <Origin ToolID="1" Connection="Output"/>
  <Destination ToolID="2" Connection="Input"/>
</Connection></Connections></AlteryxDocument>""",
        encoding="utf-8",
    )

    candidate = generate_candidate(source, "dataflow")

    assert candidate.definition_ready
    assert [group.name for group in candidate.query_groups] == ["Outer", "Inner"]
    outer, inner = candidate.query_groups
    assert outer.parent_id is None
    assert inner.parent_id == outer.id
    assert candidate.query_group_assignments["dbfileinput"] == inner.id
    assert candidate.query_group_assignments["outputdata"] == outer.id


def test_target_variance_graph_compiles_to_native_notebook() -> None:
    from etl_target_fabric.compilers.alteryx import generate_candidate

    source = Path(__file__).parents[1] / "alteryx-workflows" / "07_high_target_variance.yxmd"
    candidate = generate_candidate(source, "notebook")
    assert candidate.runtime_ready
    assert not candidate.diagnostics
    assert "Window.partitionBy" in candidate.code
    assert ".groupBy(" in candidate.code
    assert ".join(" in candidate.code
    assert "F.when" in candidate.code
    assert candidate.code.count("display(") == 2
    assert "orders" in candidate.code
    assert "region_totals" in candidate.code
    assert "Node1" not in candidate.code
    ast.parse(candidate.code)


@pytest.mark.parametrize(
    "workflow",
    [
        "08_very_high_customer_attainment.yxmd",
        "09_very_high_batch_reconcile.yxmd",
        "10_very_high_sales_pipeline.yxmd",
    ],
)
def test_very_high_workflows_compile_to_native_notebooks(workflow: str) -> None:
    from etl_target_fabric.compilers.alteryx import generate_candidate

    source = Path(__file__).parents[1] / "alteryx-workflows" / workflow
    candidate = generate_candidate(source, "notebook")
    assert candidate.runtime_ready
    assert candidate.translation_mode == "native"
    assert not candidate.diagnostics
    assert "migration_graph" not in candidate.code
    assert "RuntimeError" not in candidate.code
    ast.parse(candidate.code)


def test_append_fields_workflow_compiles_to_native_notebook() -> None:
    from etl_target_fabric.compilers.alteryx import generate_candidate

    source = Path(__file__).parents[1] / "alteryx-workflows" / "sample_merge_append_joins.yxmd"
    candidate = generate_candidate(source, "notebook")
    assert candidate.runtime_ready
    assert candidate.translation_mode == "native"
    assert ".crossJoin(" in candidate.code
    assert "F.lit(1)" in candidate.code
    ast.parse(candidate.code)


def test_snapshots_jobs_and_exports_survive_reopening(tmp_path: Path) -> None:
    from accelerator.runtime.runs import RunService

    source = tmp_path / "orders.yxmd"
    source.write_bytes(WORKFLOW)
    service = RunService(tmp_path / "state")
    preview = service.preview(source)
    source.write_text("<changed/>", encoding="utf-8")
    run = service.create_run(preview.snapshot_id)
    service.execute(run.id)
    reopened = RunService(tmp_path / "state")
    completed = reopened.get_run(run.id)
    assert completed.status == "completed"
    assert completed.result is not None
    assert completed.result.workflow_count == 1
    assert "orders.yxmd" in reopened.export_csv(run.id)
    assert reopened.generate(run.id, "notebook")[0].validation_state == "generated_unvalidated"


def test_cancelled_run_is_not_executed(tmp_path: Path) -> None:
    from accelerator.runtime.runs import RunService

    source = tmp_path / "orders.yxmd"
    source.write_bytes(WORKFLOW)
    service = RunService(tmp_path / "state")
    run = service.create_run(service.preview(source).snapshot_id)
    assert service.cancel(run.id).status == "cancelled"
    service.execute(run.id)
    assert service.get_run(run.id).status == "cancelled"


def test_run_service_context_closes_store(tmp_path: Path) -> None:
    with RunService(tmp_path / "state") as service:
        assert not service.closed
    assert service.closed
    with pytest.raises(ValueError, match="closed"):
        service.pending()


def test_dry_run_cannot_approve_unvalidated_candidates(tmp_path: Path) -> None:
    from etl_target_fabric.compilers.alteryx import generate_candidate
    from etl_target_fabric.delivery.deployer import dry_run

    source = tmp_path / "orders.yxmd"
    source.write_bytes(WORKFLOW)
    candidate = generate_candidate(source, "notebook")
    result = dry_run([candidate], approved_workspace=None, requested_workspace="dev")
    assert not result.allowed
    assert result.blockers
    approved = dry_run([candidate], approved_workspace="dev", requested_workspace="dev")
    assert approved.allowed
    assert approved.planned_mutations
    assert approved.warnings


@pytest.fixture
def local_client(tmp_path: Path) -> Iterator[TestClient]:
    previous = getattr(app.state, "run_service", None)
    app.state.run_service = RunService(tmp_path / "api-state")
    try:
        with TestClient(app, base_url="http://localhost") as client:
            yield client
    finally:
        if previous is None:
            del app.state.run_service
        else:
            app.state.run_service = previous


def wait_for_run(client: TestClient, identity: str) -> dict[str, object]:
    for _ in range(100):
        body: dict[str, object] = client.get(f"/api/runs/{identity}").json()
        if body["status"] in {"completed", "failed", "cancelled"}:
            return body
        time.sleep(0.03)
    pytest.fail("Local worker did not complete the test job")


def test_api_confirm_poll_generate_export_and_dry_run(local_client: TestClient) -> None:
    preview = local_client.post(
        "/api/snapshots/upload",
        data={"mode": "zip"},
        files=[
            ("files", ("estate.zip", archive_bytes({"orders.yxmd": WORKFLOW}), "application/zip"))
        ],
    )
    assert preview.status_code == 200
    response = local_client.post("/api/runs", json={"snapshot_id": preview.json()["snapshot_id"]})
    assert response.status_code == 202
    identity = response.json()["id"]
    assert wait_for_run(local_client, identity)["status"] == "completed"
    assert local_client.get(f"/api/runs/{identity}/candidates").status_code == 200
    assert local_client.get("/api/registry").json()["entries"]
    prefix = f"/api/runs/{identity}"
    assert local_client.get(f"{prefix}/export").json()["workflow_count"] == 1
    assert "orders.yxmd" in local_client.get(f"{prefix}/export?format=csv").text
    generated = local_client.post(f"{prefix}/generate").json()[0]
    assert generated["validation_state"] == "generated_unvalidated"
    assert generated["artifact_path"]
    assert "notebook-content.ipynb" in generated["definition_files"]
    assert not local_client.post(
        f"{prefix}/dry-run", json={"workspace": "dev", "target": "dataflow"}
    ).json()["allowed"]
    assert local_client.post(f"{prefix}/cancel").json()["status"] == "completed"
    assert local_client.get("/api/graph/schema").status_code == 200
    assert local_client.get("/").status_code in {200, 503}


def test_api_dispatches_github_deployment(
    local_client: TestClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    from accelerator.delivery.github import (
        GitHubDeploymentResult,
        GitHubDeploymentSelection,
        GitHubDeploymentService,
    )

    preview = local_client.post(
        "/api/snapshots/upload",
        data={"mode": "zip"},
        files=[
            ("files", ("estate.zip", archive_bytes({"orders.yxmd": WORKFLOW}), "application/zip"))
        ],
    )
    response = local_client.post("/api/runs", json={"snapshot_id": preview.json()["snapshot_id"]})
    identity = response.json()["id"]
    assert wait_for_run(local_client, identity)["status"] == "completed"

    captured: dict[str, object] = {}

    class FakeGitHubService:
        def deploy(self, **kwargs: object) -> GitHubDeploymentResult:
            captured.update(kwargs)
            selection = kwargs["selection"]
            assert isinstance(selection, GitHubDeploymentSelection)
            return GitHubDeploymentResult(
                deployment_id="dispatch-1",
                repository="owner/repository",
                workflow_file=".github/workflows/deploy-fabric-artifacts.yml",
                ref="main",
                target=selection.target,
            )

    monkeypatch.setattr(
        GitHubDeploymentService,
        "from_environment",
        classmethod(lambda cls: FakeGitHubService()),
    )
    monkeypatch.setenv("FABRIC_WORKSPACE_ID", "workspace-id")
    monkeypatch.setenv("ACCELERATOR_DEV_WORKSPACE", "workspace-id")
    deployed = local_client.post(
        f"/api/runs/{identity}/deploy/github",
        json={
            "repository_url": "https://github.com/owner/repository",
            "source_workflow": "orders.yxmd",
            "target": "dataflow",
            "workflow_file": ".github/workflows/deploy-fabric-artifacts.yml",
            "ref": None,
            "conflict_behavior": "Fail",
        },
    )
    assert deployed.status_code == 202, deployed.text
    assert deployed.json()["deployment_id"] == "dispatch-1"
    assert captured["workspace_id"] == "workspace-id"
    assert captured["artifact_path"] == "orders"

    workflow_name = "11_multi_container_reconciliation.yxmd"
    workflow = Path(__file__).parents[1] / "alteryx-workflows" / workflow_name
    preview = local_client.post(
        "/api/snapshots/upload",
        data={"mode": "zip"},
        files=[
            (
                "files",
                (
                    "estate.zip",
                    archive_bytes({workflow_name: workflow.read_bytes()}),
                    "application/zip",
                ),
            )
        ],
    )
    response = local_client.post("/api/runs", json={"snapshot_id": preview.json()["snapshot_id"]})
    identity = response.json()["id"]
    completed = wait_for_run(local_client, identity)
    assert completed["status"] == "completed"
    result = completed["result"]
    assert isinstance(result, dict)
    assessments = result["assessments"]
    assert isinstance(assessments, list)
    routed = WorkflowAssessmentResponse.model_validate(assessments[0])
    assert routed.recommended_target == "Dataflow Gen2"
    assert routed.target_components == ["Dataflow Gen2"]
    assert routed.estimated_effort_days == 1.4
    captured.clear()
    deployed = local_client.post(
        f"/api/runs/{identity}/deploy/github",
        json={
            "repository_url": "https://github.com/owner/repository",
            "source_workflow": workflow_name,
            "target": "dataflow",
            "workflow_file": ".github/workflows/deploy-fabric-artifacts.yml",
            "ref": None,
            "conflict_behavior": "Fail",
        },
    )
    assert deployed.status_code == 202, deployed.text
    selection = captured["selection"]
    assert isinstance(selection, GitHubDeploymentSelection)
    assert selection.target == "dataflow"
    assert str(captured["artifact_path"]) == "11_multi_container_reconciliation"

    mixed_name = "07_high_target_variance.yxmd"
    mixed = Path(__file__).parents[1] / "alteryx-workflows" / mixed_name
    preview = local_client.post(
        "/api/snapshots/upload",
        data={"mode": "zip"},
        files=[
            (
                "files",
                (
                    "estate.zip",
                    archive_bytes({mixed_name: mixed.read_bytes()}),
                    "application/zip",
                ),
            )
        ],
    )
    response = local_client.post("/api/runs", json={"snapshot_id": preview.json()["snapshot_id"]})
    identity = response.json()["id"]
    assert wait_for_run(local_client, identity)["status"] == "completed"
    captured.clear()
    deployed = local_client.post(
        f"/api/runs/{identity}/deploy/github",
        json={
            "repository_url": "https://github.com/owner/repository",
            "source_workflow": mixed_name,
            "target": "bundle",
            "workflow_file": ".github/workflows/deploy-fabric-artifacts.yml",
            "ref": None,
            "conflict_behavior": "Update",
        },
    )
    assert deployed.status_code == 202, deployed.text
    selection = captured["selection"]
    assert isinstance(selection, GitHubDeploymentSelection)
    assert selection.target == "bundle"
    assert str(captured["artifact_path"]) == "07_high_target_variance"


def test_api_dispatches_gitlab_deployment(
    local_client: TestClient,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from accelerator.delivery.gitlab import (
        GitLabDeploymentResult,
        GitLabDeploymentSelection,
        GitLabDeploymentService,
    )

    preview = local_client.post(
        "/api/snapshots/upload",
        data={"mode": "zip"},
        files=[
            (
                "files",
                ("estate.zip", archive_bytes({"orders.yxmd": WORKFLOW}), "application/zip"),
            )
        ],
    )
    response = local_client.post(
        "/api/runs",
        json={"snapshot_id": preview.json()["snapshot_id"]},
    )
    identity = response.json()["id"]
    assert wait_for_run(local_client, identity)["status"] == "completed"
    captured: dict[str, object] = {}

    class FakeGitLabService:
        def deploy(self, **kwargs: object) -> GitLabDeploymentResult:
            captured.update(kwargs)
            selection = kwargs["selection"]
            assert isinstance(selection, GitLabDeploymentSelection)
            return GitLabDeploymentResult(
                deployment_id="901",
                project="group/project",
                ci_file=".gitlab-ci.yml",
                ref="main",
                target=selection.target,
                pipeline_url="https://gitlab.com/group/project/-/pipelines/901",
            )

    monkeypatch.setattr(
        GitLabDeploymentService,
        "from_environment",
        classmethod(lambda cls: FakeGitLabService()),
    )
    monkeypatch.setenv("FABRIC_WORKSPACE_ID", "workspace-id")

    deployed = local_client.post(
        f"/api/runs/{identity}/deploy/gitlab",
        json={
            "project_url": "https://gitlab.com/group/project",
            "source_workflow": "orders.yxmd",
            "target": "dataflow",
            "ci_file": ".gitlab-ci.yml",
            "ref": None,
            "conflict_behavior": "Update",
        },
    )

    assert deployed.status_code == 202, deployed.text
    assert deployed.json()["deployment_id"] == "901"
    assert captured["workspace_id"] == "workspace-id"
    assert captured["artifact_path"] == "orders"


def test_api_local_selection_and_errors(local_client: TestClient, tmp_path: Path) -> None:
    path = tmp_path / "orders.yxmd"
    path.write_bytes(WORKFLOW)
    assert local_client.post("/api/snapshots/local", json={"path": str(path)}).status_code == 200
    assert (
        local_client.post("/api/snapshots/local", json={"path": "\\\\remote\\share"}).status_code
        == 400
    )
    assert (
        local_client.post(
            "/api/snapshots/local", json={"path": str(tmp_path / "absent")}
        ).status_code
        == 400
    )
    assert local_client.post("/api/runs", json={"snapshot_id": "a" * 64}).status_code == 404
    assert local_client.get("/api/runs/missing").status_code == 404
    assert local_client.post("/api/runs/missing/cancel").status_code == 404
    assert local_client.post("/api/runs/missing/generate").status_code == 404
    assert local_client.get("/api/runs/missing/export").status_code == 404


def test_browser_origin_host_and_token_are_enforced(local_client: TestClient) -> None:
    assert local_client.get("/health", headers={"host": "testserver"}).status_code == 400
    assert local_client.get("/health", headers={"host": "attack.invalid"}).status_code == 400
    assert (
        local_client.get("/api/session", headers={"origin": "https://attack.invalid"}).status_code
        == 403
    )
    assert (
        local_client.post(
            "/api/snapshots/local", json={"path": "."}, headers={"origin": "http://localhost"}
        ).status_code
        == 403
    )
    token = local_client.get("/api/session").json()["token"]
    assert (
        local_client.post(
            "/api/snapshots/local",
            json={"path": "\\\\remote\\share"},
            headers={"origin": "http://localhost", "x-accelerator-token": token},
        ).status_code
        == 400
    )


@pytest.mark.parametrize("name", ["CON.yxmd", ".", "same.yxmd"])
def test_upload_names_are_checked_before_writing(local_client: TestClient, name: str) -> None:
    files = [("files", (name, WORKFLOW, "application/xml"))]
    if name == "same.yxmd":
        files.append(("files", ("SAME.yxmd", WORKFLOW, "application/xml")))
    assert (
        local_client.post("/api/snapshots/upload", data={"mode": "files"}, files=files).status_code
        == 400
    )


def test_aggregate_budget_applies_to_separate_packages(tmp_path: Path) -> None:
    for name in ("one", "two"):
        (tmp_path / f"{name}.yxzp").write_bytes(archive_bytes({f"{name}.yxmd": WORKFLOW}))
    with pytest.raises(InputRejectedError):
        DiscoveryService(DiscoveryLimits(max_archive_entries=1)).discover(tmp_path)


def test_actual_stream_ratio_is_checked_even_with_small_declared_size() -> None:
    entry = zipfile.ZipInfo("flow.yxmd")
    entry.compress_size = 1
    entry.file_size = 1
    with pytest.raises(InputRejectedError):
        DiscoveryService(DiscoveryLimits(max_compression_ratio=2))._read_member(
            io.BytesIO(b"123"), entry
        )


def test_jobs_recover_expired_leases_and_cache_results(tmp_path: Path) -> None:
    source = tmp_path / "orders.yxmd"
    source.write_bytes(WORKFLOW)
    service = RunService(tmp_path / "state")
    snapshot = service.preview(source).snapshot_id
    first = service.create_run(snapshot)
    assert service._claim(first.id) == 1
    assert service._claim(first.id) is None
    with closing(sqlite3.connect(service.database)) as connection, connection:
        connection.execute("UPDATE runs SET lease=0 WHERE id=?", (first.id,))
    reopened = RunService(tmp_path / "state")
    assert first.id in reopened.pending()
    reopened.execute(first.id)
    assert reopened.get_run(first.id).status == "completed"
    second = reopened.create_run(snapshot)
    reopened.execute(second.id)
    assert reopened.get_run(second.id).cache_hits == 1
    renamed = tmp_path / "different-context.yxmd"
    renamed.write_bytes(WORKFLOW)
    third = reopened.create_run(reopened.preview(renamed).snapshot_id)
    reopened.execute(third.id)
    assert reopened.get_run(third.id).cache_hits == 0


def test_snapshot_tampering_and_newer_schema_are_rejected(tmp_path: Path) -> None:
    source = tmp_path / "orders.yxmd"
    source.write_bytes(WORKFLOW)
    service = RunService(tmp_path / "state")
    preview = service.preview(source)
    Path(preview.workflows[0].source_path).write_text("<tampered/>", encoding="utf-8")
    with pytest.raises(ValueError, match="changed"):
        service.create_run(preview.snapshot_id)
    with closing(sqlite3.connect(service.database)) as connection, connection:
        connection.execute("PRAGMA user_version=3")
    with pytest.raises(ValueError, match="schema"):
        RunService(tmp_path / "state")


def test_core_has_no_ai_network_or_legacy_imports() -> None:
    forbidden = {"httpx", "requests", "flask", "src", "openai", "anthropic", "langchain", "azure"}
    repo_root = Path(__file__).parents[1]
    targets = [
        (
            repo_root
            / "packages"
            / "etl-migration-core"
            / "src"
            / "etl_migration_core"
            / "sources"
            / "alteryx"
            / "graph.py"
        ),
        (
            repo_root
            / "packages"
            / "etl-migration-core"
            / "src"
            / "etl_migration_core"
            / "intake"
            / "discovery.py"
        ),
        (
            repo_root
            / "packages"
            / "etl-target-fabric"
            / "src"
            / "etl_target_fabric"
            / "assessment"
            / "workflow.py"
        ),
        (
            repo_root
            / "packages"
            / "etl-target-fabric"
            / "src"
            / "etl_target_fabric"
            / "compilers"
            / "alteryx.py"
        ),
        (
            repo_root
            / "packages"
            / "etl-target-fabric"
            / "src"
            / "etl_target_fabric"
            / "delivery"
            / "deployer.py"
        ),
        repo_root / "src" / "accelerator" / "runtime" / "runs.py",
    ]
    for path in targets:
        tree = ast.parse(path.read_text(encoding="utf-8"))
        for node in ast.walk(tree):
            if isinstance(node, ast.Import):
                assert all(alias.name.split(".")[0] not in forbidden for alias in node.names)
            elif isinstance(node, ast.ImportFrom) and node.module:
                assert node.module.split(".")[0] not in forbidden


@pytest.mark.parametrize(
    "content",
    [
        WORKFLOW.replace(b'ToolID="2"', b'ToolID="1"', 1),
        WORKFLOW.replace(b'<Destination ToolID="2"', b'<Destination ToolID="99"'),
        b"<AlteryxDocument>" + b"<Nested>" * 66 + b"</Nested>" * 66 + b"</AlteryxDocument>",
    ],
)
def test_invalid_graphs_are_isolated(tmp_path: Path, content: bytes) -> None:
    path = tmp_path / "invalid.yxmd"
    path.write_bytes(content)
    with pytest.raises(WorkflowParseError):
        assess_workflow(path)


def test_events_and_unsupported_expressions_generate_scaffolds(tmp_path: Path) -> None:
    from etl_target_fabric.compilers.alteryx import generate_candidate

    path = tmp_path / "events.yxmd"
    path.write_bytes(
        WORKFLOW.replace(b"</AlteryxDocument>", b"<Events><Event/></Events></AlteryxDocument>")
    )
    notebook = generate_candidate(path, "notebook")
    assert not notebook.deployable
    assert not notebook.runtime_ready
    ast.parse(notebook.code)
    path.write_bytes(WORKFLOW.replace(b"[Amount] &gt; 0", b"RunCommand('unsafe')"))
    dataflow = generate_candidate(path, "dataflow")
    assert not dataflow.deployable
    assert not dataflow.runtime_ready
    assert "MigrationScaffold" in dataflow.code


def test_packages_are_byte_stable_and_contain_fabric_definition_files(tmp_path: Path) -> None:
    source = tmp_path / "orders.yxmd"
    source.write_bytes(WORKFLOW)
    service = RunService(tmp_path / "state")
    run = service.create_run(service.preview(source).snapshot_id)
    service.execute(run.id)
    for target, filename in (
        ("notebook", "notebook-content.ipynb"),
        ("dataflow", "dataflow-mashup.pq"),
    ):
        if target == "notebook":
            content = service.candidate_package(run.id, "notebook")
            assert content == service.candidate_package(run.id, "notebook")
        else:
            content = service.candidate_package(run.id, "dataflow")
            assert content == service.candidate_package(run.id, "dataflow")
        with zipfile.ZipFile(io.BytesIO(content)) as archive:
            matching = [name for name in archive.namelist() if name.endswith("/" + filename)]
            assert matching
            manifest_name = next(
                name for name in archive.namelist() if name.endswith(f"/{target}-manifest.json")
            )
            manifest = json.loads(archive.read(manifest_name))
            assert manifest["validation_state"] == "generated_unvalidated"
            assert manifest["deployable"]
            assert any(name.endswith(f"/{target}-create-item.json") for name in archive.namelist())


def test_workflow_bundle_is_byte_stable_and_contains_manual_install_guide(
    tmp_path: Path,
) -> None:
    source = tmp_path / "orders.yxmd"
    source.write_bytes(WORKFLOW)
    service = RunService(tmp_path / "state", artifact_root=tmp_path / "artifacts")
    run = service.create_run(service.preview(source).snapshot_id)
    service.execute(run.id)

    content, filename = service.workflow_package(run.id, "orders.yxmd")

    assert filename == "orders-fabric-bundle.zip"
    assert content == service.workflow_package(run.id, "orders.yxmd")[0]
    with zipfile.ZipFile(io.BytesIO(content)) as archive:
        assert "README.md" in archive.namelist()
        assert "dataflow-create-item.json" in archive.namelist()
        assert "notebook-create-item.json" in archive.namelist()
        guide = archive.read("README.md").decode("utf-8")
        assert "# orders Fabric workflow bundle" in guide
        assert "## Manual deployment" in guide
        assert "az login" in guide
        assert "Independent semantic validation remains required" in guide
    with pytest.raises(ValueError, match="Workflow was not found"):
        service.workflow_package(run.id, "missing.yxmd")


def test_api_downloads_one_workflow_bundle(
    local_client: TestClient,
    tmp_path: Path,
) -> None:
    source = tmp_path / "orders.yxmd"
    source.write_bytes(WORKFLOW)
    snapshot = local_client.post(
        "/api/snapshots/local",
        json={"path": str(source)},
    ).json()
    run = local_client.post(
        "/api/runs",
        json={"snapshot_id": snapshot["snapshot_id"]},
    ).json()
    wait_for_run(local_client, run["id"])

    response = local_client.get(
        f"/api/runs/{run['id']}/bundle",
        params={"workflow": "orders.yxmd"},
    )

    assert response.status_code == 200
    assert response.headers["content-type"] == "application/zip"
    assert (
        response.headers["content-disposition"]
        == 'attachment; filename="orders-fabric-bundle.zip"'
    )
    with zipfile.ZipFile(io.BytesIO(response.content)) as archive:
        assert "README.md" in archive.namelist()


def test_stale_worker_cannot_commit_results(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    source = tmp_path / "orders.yxmd"
    source.write_bytes(WORKFLOW)
    service = RunService(tmp_path / "state")
    run = service.create_run(service.preview(source).snapshot_id)
    original = service._assess_item

    def fence_worker(
        item: WorkflowCandidateResponse,
    ) -> tuple[list[WorkflowAssessmentResponse], str | None, int]:
        with closing(sqlite3.connect(service.database)) as connection, connection:
            connection.execute("UPDATE runs SET epoch=epoch+1 WHERE id=?", (run.id,))
        return original(item)

    monkeypatch.setattr(service, "_assess_item", fence_worker)
    service.execute(run.id)
    current = service.get_run(run.id)
    assert current.processed == 0
    assert current.result is None


@pytest.mark.parametrize("target", ["notebook", "dataflow"])
def test_select_preview_golden_and_unsupported_options(tmp_path: Path, target: str) -> None:
    from etl_target_fabric.compilers.alteryx import generate_candidate

    path = tmp_path / "select.yxmd"
    content = WORKFLOW.replace(b"Filter.Filter", b"Select.Select").replace(
        b"<Expression>[Amount] &gt; 0</Expression>",
        b'<SelectFields><SelectField field="Amount" selected="True"/></SelectFields>',
    )
    path.write_bytes(content)
    candidate = generate_candidate(path, "notebook" if target == "notebook" else "dataflow")
    assert candidate.validation_state == "generated_unvalidated"
    if target == "notebook":
        assert 'df = df.select(*["Amount"])' in candidate.code
    else:
        assert 'Table.SelectColumns(inputdata, {"Amount"})' in candidate.code
    path.write_bytes(content.replace(b'field="Amount"', b'field="Amount" type="Double"'))
    assert not generate_candidate(
        path, "notebook" if target == "notebook" else "dataflow"
    ).deployable


@pytest.mark.parametrize("name", ["=formula.yxmd", "  =formula.yxmd"])
def test_csv_formula_injection_is_defused(tmp_path: Path, name: str) -> None:
    source = tmp_path / name
    source.write_bytes(WORKFLOW)
    service = RunService(tmp_path / "state")
    run = service.create_run(service.preview(source).snapshot_id)
    service.execute(run.id)
    assert "'" + name in service.export_csv(run.id)


def test_repeated_configuration_is_inventoried_in_scaffold(tmp_path: Path) -> None:
    from etl_target_fabric.compilers.alteryx import generate_candidate

    path = tmp_path / "repeated.yxmd"
    path.write_bytes(
        WORKFLOW.replace(b"<File>orders.csv</File>", b"<File>one.csv</File><File>two.csv</File>")
    )
    assert assess_workflow(path).tool_count == 2
    candidate = generate_candidate(path, "notebook")
    assert not candidate.deployable
    assert not candidate.runtime_ready
    assert any("Repeated" in issue for issue in candidate.diagnostics)


def test_configuration_connections_are_not_canvas_edges(tmp_path: Path) -> None:
    path = tmp_path / "output-order.yxmd"
    path.write_bytes(
        WORKFLOW.replace(
            b"<File>orders.csv</File>",
            b"<File>orders.csv</File><OutputOrder><Connection value='1'/></OutputOrder>",
        )
    )
    assessment = assess_workflow(path)
    assert assessment.connection_count == 1
    assert assessment.tool_count == 2


def test_m_literal_escape_preserves_hash_sequences(tmp_path: Path) -> None:
    from etl_target_fabric.compilers.alteryx import generate_candidate

    path = tmp_path / "hash-name.yxmd"
    path.write_bytes(WORKFLOW.replace(b"[Amount]", b"[#(lf)]"))
    candidate = generate_candidate(path, "dataflow")
    assert candidate.validation_state == "generated_unvalidated"
    assert '"#(#)(lf)"' in candidate.code


def test_zero_compressed_nonempty_stream_is_rejected() -> None:
    entry = zipfile.ZipInfo("flow.yxmd")
    entry.compress_size = 0
    with pytest.raises(InputRejectedError):
        DiscoveryService()._read_member(io.BytesIO(b"x"), entry)


def test_unreadable_workflow_does_not_abort_other_files(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    import etl_migration_core.intake.discovery as discovery

    (tmp_path / "a.yxmd").write_bytes(WORKFLOW)
    (tmp_path / "b.yxmd").write_bytes(WORKFLOW)
    original = discovery._hash_stream
    calls = 0

    def read(stream: IO[bytes]) -> str:
        nonlocal calls
        calls += 1
        if calls == 1:
            stream.close()
            raise PermissionError("Synthetic locked workflow")
        return original(stream)

    monkeypatch.setattr(discovery, "_hash_stream", read)
    summary = DiscoveryService().discover(tmp_path)
    assert summary.workflow_count == 1
    assert summary.skipped[0].reason.value == "unreadable_input"


def test_waiting_batch_renews_its_fenced_lease(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    import accelerator.runtime.runs as runs

    source = tmp_path / "orders.yxmd"
    source.write_bytes(WORKFLOW)
    service = RunService(tmp_path / "state")
    run = service.create_run(service.preview(source).snapshot_id)
    entered, release = Event(), Event()
    original = service._assess_item

    def blocked(
        item: WorkflowCandidateResponse,
    ) -> tuple[list[WorkflowAssessmentResponse], str | None, int]:
        entered.set()
        assert release.wait(10)
        return original(item)

    def fast_wait(
        pending: set[Future[tuple[list[WorkflowAssessmentResponse], str | None, int]]],
        timeout: float,
    ) -> tuple[
        set[Future[tuple[list[WorkflowAssessmentResponse], str | None, int]]],
        set[Future[tuple[list[WorkflowAssessmentResponse], str | None, int]]],
    ]:
        assert timeout == 5
        return wait(pending, timeout=0.01)

    monkeypatch.setattr(service, "_assess_item", blocked)
    monkeypatch.setattr(runs, "wait", fast_wait)
    worker = Thread(target=service.execute, args=(run.id,))
    worker.start()
    try:
        assert entered.wait(2)
        with closing(sqlite3.connect(service.database)) as connection, connection:
            connection.execute("UPDATE runs SET lease=0 WHERE id=?", (run.id,))
        deadline = time.monotonic() + 2
        renewed = False
        while time.monotonic() < deadline:
            with closing(sqlite3.connect(service.database)) as connection, connection:
                lease = connection.execute(
                    "SELECT lease FROM runs WHERE id=?", (run.id,)
                ).fetchone()[0]
            if lease > time.time() + 200:
                renewed = True
                break
            time.sleep(0.01)
        assert renewed
    finally:
        release.set()
        worker.join(10)
    assert not worker.is_alive()
    assert service.get_run(run.id).status == "completed"


def test_canvas_annotations_do_not_change_score_or_block_preview(tmp_path: Path) -> None:
    from etl_target_fabric.compilers.alteryx import generate_candidate

    path = tmp_path / "annotated.yxmd"
    path.write_bytes(WORKFLOW)
    before = assess_workflow(path)
    path.write_bytes(
        WORKFLOW.replace(
            b"</Nodes>",
            b'<Node ToolID="3"><GuiSettings Plugin="AlteryxGuiToolkit.TextBox.TextBox"/>'
            b"</Node></Nodes>",
        )
    )
    after = assess_workflow(path)
    assert after.complexity_score == before.complexity_score
    assert after.estimated_effort_days == before.estimated_effort_days
    assert generate_candidate(path, "notebook").validation_state == "generated_unvalidated"


def test_disabled_workflow_events_do_not_block_generation(tmp_path: Path) -> None:
    from etl_target_fabric.compilers.alteryx import generate_candidate

    path = tmp_path / "events-disabled.yxmd"
    path.write_bytes(
        WORKFLOW.replace(
            b"</AlteryxDocument>",
            b"<Properties><Events><Enabled value='False'/></Events></Properties></AlteryxDocument>",
        )
    )
    candidate = generate_candidate(path, "notebook")
    assert candidate.validation_state == "generated_unvalidated"
    assert not any("events" in value.casefold() for value in candidate.diagnostics)


def test_real_designer_workflow_with_empty_enabled_events_and_anchor_join_compiles() -> None:
    from etl_target_fabric.compilers.alteryx import generate_candidate

    workflow = Path(__file__).parents[1] / "alteryx-workflows" / "my_alteryx-workflow.yxmd"
    dataflow = generate_candidate(workflow, "dataflow")
    notebook = generate_candidate(workflow, "notebook")

    assert dataflow.deployable
    assert dataflow.definition_ready
    assert dataflow.validation_state == "generated_unvalidated"
    assert "source_queries['1']" in dataflow.required_bindings
    assert "source_queries['11']" in dataflow.required_bindings
    assert "Table.NestedJoin" in dataflow.code

    assert notebook.deployable
    assert notebook.definition_ready
    assert "source_paths['1']" in notebook.required_bindings
    assert "source_paths['11']" in notebook.required_bindings
    assert ".join(" in notebook.code


def test_unique_output_anchor_and_date_regex_compile_natively(tmp_path: Path) -> None:
    from etl_target_fabric.compilers.alteryx import generate_candidate

    unique = tmp_path / "unique.yxmd"
    unique.write_bytes(
        WORKFLOW.replace(
            b"Filter.Filter",
            b"Unique.Unique",
        )
        .replace(
            b"<Expression>[Amount] &gt; 0</Expression>",
            b"<UniqueFields><Field field='CustomerID'/></UniqueFields>",
        )
        .replace(b'Connection="Output"', b'Connection="Unique"', 1)
    )
    assert generate_candidate(unique, "notebook").definition_ready

    date_regex = tmp_path / "date-regex.yxmd"
    date_regex.write_text(
        """<AlteryxDocument><Nodes>
        <Node ToolID="1"><GuiSettings Plugin="AlteryxBasePluginsGui.TextInput.TextInput"/>
          <Properties><Configuration><Fields><Field name="Date"/><Field name="SKU"/></Fields>
          <Data><r><c>2026-01-12</c><c>SKU-100</c></r></Data></Configuration></Properties></Node>
        <Node ToolID="2"><GuiSettings Plugin="AlteryxBasePluginsGui.DateTime.DateTime"/>
          <Properties><Configuration><IsFrom value="True"/><InputFieldName>Date</InputFieldName>
          <Format>yyyy-MM-dd</Format><OutputFieldName>Parsed</OutputFieldName></Configuration></Properties></Node>
        <Node ToolID="3"><GuiSettings Plugin="AlteryxBasePluginsGui.RegEx.RegEx"/>
          <Properties><Configuration><Field>SKU</Field><RegExExpression value="([A-Z]+)-([0-9]+)"/>
          <CaseInsensitve value="False"/><Method>ParseComplex</Method>
          <ParseComplex><Field field="Family"/><Field field="Number"/></ParseComplex>
          <Replace expression=""/><ParseSimple/><Match/></Configuration></Properties></Node>
        </Nodes><Connections>
          <Connection><Origin ToolID="1" Connection="Output"/>
          <Destination ToolID="2" Connection="Input"/></Connection>
          <Connection><Origin ToolID="2" Connection="Output"/>
          <Destination ToolID="3" Connection="Input"/></Connection>
        </Connections></AlteryxDocument>""",
        encoding="utf-8",
    )
    candidate = generate_candidate(date_regex, "notebook")
    assert candidate.definition_ready
    assert "to_date" in candidate.code
    assert "regexp_extract" in candidate.code
    dataflow = generate_candidate(date_regex, "dataflow")
    assert dataflow.definition_ready
    assert dataflow.translation_mode == "native"
    assert dataflow.runtime_ready
    assert "Date.FromText" in dataflow.code
    assert "Text.BeforeDelimiter" in dataflow.code
    assert dataflow.definition_queries == ["regex"]
    assert "textinput = #table" in dataflow.code
    assert "datetime = Table.AddColumn" in dataflow.code


def test_generated_artifacts_are_persisted_under_project_folder(tmp_path: Path) -> None:
    source = tmp_path / "orders.yxmd"
    source.write_bytes(WORKFLOW)
    service = RunService(tmp_path / "state", artifact_root=tmp_path / "generated-fabric-workflows")
    run = service.create_run(service.preview(source).snapshot_id)
    service.execute(run.id)

    result = service.write_artifacts(run.id, "notebook")

    assert result.root == (tmp_path / "generated-fabric-workflows").resolve()
    assert (result.root / "artifact-index-notebook.json").is_file()
    plan = json.loads((result.root / "deployment-plan.json").read_text())
    assert plan["native_ready_count"] == 1
    assert plan["workflows"][0]["selected_components"][0]["target"] == "notebook"
    assert (
        json.loads((tmp_path / "generated-fabric-workflows" / "latest.json").read_text())["run_id"]
        == run.id
    )
    assert (tmp_path / "generated-fabric-workflows" / "DEPLOYMENT.txt").is_file()
    notebook = result.root / "orders" / "notebook-content.ipynb"
    request = notebook.parent / "notebook-create-item.json"
    assert request.is_file()
    body = json.loads(request.read_text(encoding="utf-8"))
    assert body["type"] == "Notebook"
    assert body["definition"]["format"] == "ipynb"
    assert body["definition"]["parts"][0]["path"] == "notebook-content.ipynb"
    for part in body["definition"]["parts"]:
        decoded = base64.b64decode(part["payload"]).decode("utf-8")
        local_name = "notebook.platform.json" if part["path"] == ".platform" else part["path"]
        assert decoded == (notebook.parent / local_name).read_text(encoding="utf-8")
    notebook_json = json.loads(notebook.read_text(encoding="utf-8"))
    notebook_code = "\n".join(
        "".join(cell["source"]) for cell in notebook_json["cells"] if cell["cell_type"] == "code"
    )
    ast.parse(notebook_code)
    dataflow = service.write_artifacts(run.id, "dataflow")
    mashup = (dataflow.root / "orders" / "dataflow-mashup.pq").read_text(encoding="utf-8")
    assert "Previous" not in mashup
    assert "shared filter = let" in mashup
    assert "inputdata = Record.Field(SourceBindings" in mashup
    assert "filter = Table.SelectRows(inputdata" in mashup
    with pytest.raises(ValueError, match="Run ID"):
        service.write_artifacts("../outside", "notebook")


def test_multi_query_dataflow_definition_preserves_query_load_settings(tmp_path: Path) -> None:
    source = (
        Path(__file__).parents[1]
        / "alteryx-workflows"
        / "11_multi_container_reconciliation.yxmd"
    )
    service = RunService(tmp_path / "state", artifact_root=tmp_path / "artifacts")
    run = service.create_run(service.preview(source).snapshot_id)
    service.execute(run.id)

    result = service.write_artifacts(run.id, "dataflow")
    folder = result.root / "11_multi_container_reconciliation"
    mashup = (folder / "dataflow-mashup.pq").read_text(encoding="utf-8")
    metadata = json.loads(
        (folder / "dataflow-queryMetadata.json").read_text(encoding="utf-8")
    )
    create_request = json.loads(
        (folder / "dataflow-create-item.json").read_text(encoding="utf-8")
    )

    assert mashup.startswith("section Section1;")
    assert mashup.count("section Section1;") == 1
    assert set(metadata["queriesMetadata"]) == set(result.candidates[0].definition_queries)
    groups = {group["id"]: group for group in metadata["queryGroups"]}
    assert [group["name"] for group in metadata["queryGroups"]] == [
        "00 Source Files",
        "01 Ledger Alpha and Beta",
        "02 Reference Enrichment",
        "03 Settlement Reconciliation",
        "04 Final Outputs",
        "05 Destinations",
    ]
    assert all(group["parentId"] is None for group in groups.values())
    assert metadata["computeEngineSettings"] == {"allowFastCopy": False}
    loaded = set(result.candidates[0].loaded_queries)
    assert loaded
    for query_name, query in metadata["queriesMetadata"].items():
        if query_name == "SourceBindings":
            assert "queryGroupId" not in query
        else:
            assert query["queryGroupId"] in groups
        assert query["loadEnabled"] is False
    assert [part["path"] for part in create_request["definition"]["parts"]] == [
        "mashup.pq",
        "queryMetadata.json",
        ".platform",
    ]


def test_informatica_dataflow_definition_disables_staging(tmp_path: Path) -> None:
    source = (
        Path(__file__).parent
        / "fixtures"
        / "powercenter"
        / "router_validation_repository.xml"
    )
    service = RunService(tmp_path / "state", artifact_root=tmp_path / "artifacts")
    run = service.create_run(service.preview(source).snapshot_id)
    service.execute(run.id)

    result = service.write_artifacts(run.id, "dataflow")
    folder = result.root / "informatica-powercenter" / "wf_STG_Ledger_Validation"
    metadata = json.loads(
        (folder / "dataflow-queryMetadata.json").read_text(encoding="utf-8")
    )
    manifest = json.loads(
        (folder / "dataflow-manifest.json").read_text(encoding="utf-8")
    )

    assert metadata["computeEngineSettings"] == {"allowFastCopy": False}
    assert manifest["definition_queries"] == [
        "SourceBindings",
        "exp_date_validation",
        "rtr_ledger_default1",
        "stg_ledger_content",
        "unprocessed_north_file_list",
        "unprocessed_south_file_list",
    ]
    assert set(manifest["loaded_queries"]).issubset(metadata["queriesMetadata"])
    assert all(
        query["loadEnabled"] is False
        for query in metadata["queriesMetadata"].values()
    )


def test_alteryx_linear_dataflow_steps_group_into_single_query() -> None:
    from etl_target_fabric.compilers.alteryx import generate_candidate

    source = Path(__file__).parents[1] / "alteryx-workflows" / "02_low_west_sample.yxmd"
    candidate = generate_candidate(source, "dataflow")

    assert candidate.definition_queries == ["west_sample"]
    assert candidate.loaded_queries == ["west_sample"]
    assert candidate.code.count("shared ") == 1
    assert "shared west_sample = let" in candidate.code
    for step in ("orders =", "west_only =", "add_tax =", "top_3_rows ="):
        assert step in candidate.code


def test_generated_notebook_is_documented_and_split_into_focused_cells(
    tmp_path: Path,
) -> None:
    source = (
        Path(__file__).parents[1]
        / "alteryx-workflows"
        / "11_multi_container_reconciliation.yxmd"
    )
    service = RunService(tmp_path / "state", artifact_root=tmp_path / "artifacts")
    run = service.create_run(service.preview(source).snapshot_id)
    service.execute(run.id)

    result = service.write_artifacts(run.id, "notebook")
    notebook = json.loads(
        (
            result.root
            / "11_multi_container_reconciliation"
            / "notebook-content.ipynb"
        ).read_text(encoding="utf-8")
    )
    markdown = "\n".join(
        "".join(cell["source"])
        for cell in notebook["cells"]
        if cell["cell_type"] == "markdown"
    )
    code_cells = [
        cell for cell in notebook["cells"] if cell["cell_type"] == "code"
    ]

    for heading in (
        "# 11_multi_container_reconciliation",
        "## How to use this notebook",
        "## Runtime imports",
        "## Source configuration",
        "## Source ingestion",
        "## Transformations",
        "## Output preview",
    ):
        assert heading in markdown
    assert len(code_cells) >= 8
    assert any("source_paths = {" in "".join(cell["source"]) for cell in code_cells)
    assert max(len(cell["source"]) for cell in code_cells) <= 16
    assert all(
        line.endswith("\n")
        for cell in notebook["cells"]
        for line in cell["source"]
    )
    ast.parse(
        "\n".join(
            "".join(cell["source"]) for cell in code_cells
        )
    )


@pytest.mark.parametrize(
    "workflow",
    ["07_high_target_variance.yxmd", "10_very_high_sales_pipeline.yxmd"],
)
def test_mixed_redesign_workflows_generate_three_item_bundles(
    tmp_path: Path, workflow: str
) -> None:
    source = Path(__file__).parents[1] / "alteryx-workflows" / workflow
    service = RunService(tmp_path / "state", artifact_root=tmp_path / "artifacts")
    run = service.create_run(service.preview(source).snapshot_id)
    service.execute(run.id)
    completed = service.get_run(run.id)
    assert completed.result is not None
    assessment = completed.result.assessments[0]
    assert assessment.recommended_target == "Mixed Fabric solution"
    assert assessment.target_components == [
        "Dataflow Gen2",
        "Fabric Notebook",
        "Fabric Pipeline",
    ]

    service.write_artifacts(run.id, "notebook")
    service.write_artifacts(run.id, "dataflow")
    folder = tmp_path / "artifacts" / source.stem
    bundle = json.loads((folder / "deployment-bundle.json").read_text(encoding="utf-8"))
    pipeline = json.loads(
        (folder / "pipeline-content.json").read_text(encoding="utf-8")
    )
    plan = json.loads(
        (tmp_path / "artifacts" / "deployment-plan.json").read_text(encoding="utf-8")
    )

    assert bundle["deploymentOrder"] == ["Dataflow", "Notebook", "DataPipeline"]
    assert [item["type"] for item in bundle["items"]] == [
        "Dataflow",
        "Notebook",
        "DataPipeline",
    ]
    activities = pipeline["properties"]["activities"]
    assert [activity["type"] for activity in activities] == [
        "RefreshDataflow",
        "TridentNotebook",
    ]
    assert activities[0]["typeProperties"]["dataflowId"] == "{{DATAFLOW_ITEM_ID}}"
    assert activities[1]["typeProperties"]["notebookId"] == "{{NOTEBOOK_ITEM_ID}}"
    assert activities[1]["dependsOn"] == [
        {
            "activity": "Run Dataflow Gen2",
            "dependencyConditions": ["Succeeded"],
        }
    ]
    selected = plan["workflows"][0]["selected_components"]
    assert [component["type"] for component in selected] == [
        "Dataflow",
        "Notebook",
        "DataPipeline",
    ]
    assert plan["workflows"][0]["pipeline_required"] is True
    guide = (folder / "README.md").read_text(encoding="utf-8")
    assert "### Pipeline dependency IDs" in guide
    assert "{{DATAFLOW_ITEM_ID}}" in guide
    package, filename = service.workflow_package(run.id, workflow)
    assert filename == f"{source.stem}-fabric-bundle.zip"
    with zipfile.ZipFile(io.BytesIO(package)) as archive:
        assert {
            "README.md",
            "dataflow-create-item.json",
            "notebook-create-item.json",
            "pipeline-create-item.json",
            "deployment-bundle.json",
        }.issubset(archive.namelist())


def test_uri_userinfo_is_redacted_without_reading_the_source(tmp_path: Path) -> None:
    path = tmp_path / "source.yxmd"
    path.write_bytes(
        WORKFLOW.replace(b"orders.csv", b"https://sensitive-token@example.invalid/data.csv")
    )
    result = assess_workflow(path)
    assert result.data_sources == ("https://[redacted]@example.invalid/data.csv",)


def test_readonly_evidence_is_identity_bound_and_redacted(
    local_client: TestClient,
    tmp_path: Path,
) -> None:
    path = tmp_path / "evidence.yxmd"
    path.write_bytes(
        WORKFLOW.replace(
            b"</AlteryxDocument>",
            b"<MetaInfo><Description>password=should-not-leak</Description></MetaInfo>"
            b"</AlteryxDocument>",
        )
    )
    snapshot = local_client.post("/api/snapshots/local", json={"path": str(path)}).json()
    run = local_client.post("/api/runs", json={"snapshot_id": snapshot["snapshot_id"]}).json()
    wait_for_run(local_client, run["id"])
    response = local_client.get(f"/api/runs/{run['id']}/evidence?workflow_index=0")
    assert response.status_code == 200
    assert response.headers["cache-control"] == "no-store"
    body = response.json()
    assert body["schema_version"] == "1.1.0"
    assert body["run_id"] == run["id"]
    assert body["snapshot_id"] == snapshot["snapshot_id"]
    assert body["workflows"][0]["workflow_path"] == "evidence.yxmd"
    assert body["workflows"][0]["layout_source"] == "derived"
    assert len(body["workflows"][0]["nodes"]) == 2
    assert body["workflows"][0]["nodes"][0]["label"] == ""
    assert body["workflows"][0]["nodes"][0]["width"] is None
    assert "should-not-leak" not in response.text
    assert local_client.get(f"/api/runs/{run['id']}/evidence?workflow_index=999").status_code == 404


def test_evidence_preserves_alteryx_annotations_and_container_dimensions() -> None:
    from etl_portfolio_assessment.evidence.extractor import workflow_evidence

    source = (
        Path(__file__).parents[1]
        / "alteryx-workflows"
        / "11_multi_container_reconciliation.yxmd"
    )
    evidence = workflow_evidence(source, source.name, 0)
    container = next(node for node in evidence.nodes if node.id == "100")
    input_node = next(node for node in evidence.nodes if node.id == "1")

    assert evidence.layout_source == "source"
    assert container.name == "ToolContainer"
    assert container.label == "00 Source Files"
    assert (container.x, container.y, container.width, container.height) == (
        40.0,
        55.0,
        335.0,
        915.0,
    )
    assert input_node.label == "src_BusinessDate"
    assert (input_node.x, input_node.y) == (75.0, 110.0)
    assert input_node.width is None
    assert input_node.height is None


def test_evidence_errors_are_not_cached(local_client: TestClient, tmp_path: Path) -> None:
    response = local_client.get("/api/runs/missing/evidence")
    assert response.status_code == 404
    assert response.headers["cache-control"] == "no-store"
    path = tmp_path / "evidence.yxmd"
    path.write_bytes(WORKFLOW)
    preview = local_client.post("/api/snapshots/local", json={"path": str(path)}).json()
    run = local_client.post("/api/runs", json={"snapshot_id": preview["snapshot_id"]}).json()
    wait_for_run(local_client, run["id"])
    Path(preview["workflows"][0]["source_path"]).write_bytes(b"<changed/>")
    response = local_client.get(f"/api/runs/{run['id']}/evidence")
    assert response.status_code == 409
    assert response.headers["cache-control"] == "no-store"


def test_evidence_redacts_before_truncation_and_withholds_sensitive_expressions() -> None:
    from etl_portfolio_assessment.evidence.extractor import safe_expression, safe_text

    value = "https://sensitiveuser:secretpassword@example.invalid/data"
    assert "sensitiveuser" not in safe_text(value, 30)
    assert "secretpassword" not in safe_text(value, 30)
    assert (
        safe_expression('[API key] = "should-not-leak"')
        == "[Credential-bearing expression withheld]"
    )
