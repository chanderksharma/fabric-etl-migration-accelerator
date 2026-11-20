"""API contract tests."""

from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from accelerator.api import app


def test_health_reports_version() -> None:
    response = TestClient(app, base_url="http://localhost").get("/health")

    assert response.status_code == 200
    assert response.json()["status"] == "ok"


def test_desktop_session_token_protects_the_embedded_api(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("ACCELERATOR_DESKTOP_TOKEN", "desktop-test-token")
    client = TestClient(app, base_url="http://localhost")

    assert client.get("/health").status_code == 401
    assert (
        client.get(
            "/health",
            headers={"x-accelerator-desktop-token": "wrong-token"},
        ).status_code
        == 401
    )
    assert (
        client.get(
            "/health",
            headers={"x-accelerator-desktop-token": "desktop-test-token"},
        ).status_code
        == 200
    )

    bootstrap = client.get(
        "/",
        params={"desktop_token": "desktop-test-token"},
        follow_redirects=False,
    )
    assert bootstrap.status_code == 307
    assert "accelerator-desktop-token=" in bootstrap.headers["set-cookie"]
    assert client.get("/health").status_code == 200


def test_desktop_session_rejects_query_tokens_outside_root(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("ACCELERATOR_DESKTOP_TOKEN", "desktop-test-token")

    response = TestClient(app, base_url="http://localhost").get(
        "/health",
        params={"desktop_token": "desktop-test-token"},
    )

    assert response.status_code == 401


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


def test_browse_local_folder_returns_picked_path_and_handles_unavailable(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    import accelerator.api as api_module

    client = TestClient(app, base_url="http://localhost")

    monkeypatch.setattr(api_module, "_pick_local_folder", lambda: "C:\\workflows")
    picked = client.post("/api/snapshots/browse-folder")
    assert picked.status_code == 200
    assert picked.json() == {"path": "C:\\workflows"}

    monkeypatch.setattr(api_module, "_pick_local_folder", lambda: None)
    cancelled = client.post("/api/snapshots/browse-folder")
    assert cancelled.status_code == 200
    assert cancelled.json() == {"path": None}

    def fail_picker() -> str | None:
        raise RuntimeError("Native folder picker is unavailable")

    monkeypatch.setattr(api_module, "_pick_local_folder", fail_picker)
    unavailable = client.post("/api/snapshots/browse-folder")
    assert unavailable.status_code == 501
