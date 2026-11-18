"""API contract tests."""

from pathlib import Path

from fastapi.testclient import TestClient

from accelerator.api import app


def test_health_reports_version() -> None:
    response = TestClient(app, base_url="http://localhost").get("/health")

    assert response.status_code == 200
    assert response.json()["status"] == "ok"


def test_preview_returns_shared_discovery_contract(tmp_path: Path) -> None:
    workflow = tmp_path / "sample.yxmd"
    workflow.write_text("<Workflow />", encoding="utf-8")

    response = TestClient(app, base_url="http://localhost").get(
        "/api/intake/preview", params={"path": str(tmp_path)}
    )

    assert response.status_code == 200
    body = response.json()
    assert body["workflow_count"] == 1
    assert body["workflows"][0]["display_path"] == "sample.yxmd"


def test_preview_rejects_missing_path() -> None:
    response = TestClient(app, base_url="http://localhost").get(
        "/api/intake/preview",
        params={"path": "Z:\\a-path-that-does-not-exist"},
    )

    assert response.status_code == 400
    assert response.json()["detail"]["reason"] == "missing_path"


def test_upload_preview_processes_browser_files() -> None:
    response = TestClient(app, base_url="http://localhost").post(
        "/api/intake/upload",
        data={"mode": "files"},
        files=[
            ("files", ("sample.yxmd", b"<Workflow />", "application/xml")),
            ("files", ("notes.txt", b"skip", "text/plain")),
        ],
    )

    assert response.status_code == 200
    body = response.json()
    assert body["workflow_count"] == 1
    assert body["skipped_count"] == 1


def test_upload_preview_rejects_path_traversal() -> None:
    response = TestClient(app, base_url="http://localhost").post(
        "/api/intake/upload",
        data={"mode": "files"},
        files=[("files", ("../escape.yxmd", b"<Workflow />", "application/xml"))],
    )

    assert response.status_code == 400


def test_upload_assessment_returns_deterministic_result() -> None:
    workflow = b"""
    <AlteryxDocument>
      <Nodes>
        <Node ToolID="1"><GuiSettings Plugin="AlteryxBasePluginsGui.Filter.Filter" /></Node>
      </Nodes>
    </AlteryxDocument>
    """
    response = TestClient(app, base_url="http://localhost").post(
        "/api/assessment/upload",
        data={"mode": "files"},
        files=[("files", ("sample.yxmd", workflow, "application/xml"))],
    )

    assert response.status_code == 200
    body = response.json()
    assert body["workflow_count"] == 1
    assert body["assessments"][0]["recommended_target"] == "Dataflow Gen2"
