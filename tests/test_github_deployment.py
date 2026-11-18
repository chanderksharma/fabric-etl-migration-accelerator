"""Tests for GitHub App workflow bootstrap and dispatch."""

import subprocess
from typing import Any

import pytest

from accelerator.github_deployment import (
    APPROVED_WORKFLOW_PATH,
    DeploymentTarget,
    GitHubDeploymentError,
    GitHubDeploymentSelection,
    GitHubDeploymentService,
    parse_github_repository,
)


def test_repository_url_validation() -> None:
    assert parse_github_repository("https://github.com/owner/repository.git") == (
        "owner/repository"
    )
    with pytest.raises(ValueError, match="HTTPS GitHub"):
        parse_github_repository("owner/repository")
    with pytest.raises(ValueError, match="HTTPS GitHub"):
        parse_github_repository("https://example.com/owner/repository")


def test_pipeline_target_uses_fabric_data_pipeline_name() -> None:
    selection = GitHubDeploymentSelection(
        repository_url="https://github.com/owner/repository",
        source_workflow="tf_orders",
        target="pipeline",
    )

    assert selection.target == "pipeline"


@pytest.mark.parametrize(
    ("target", "workflow_target"),
    [("dataflow", "Dataflow"), ("pipeline", "DataPipeline")],
)
def test_dispatches_existing_workflow(
    monkeypatch: pytest.MonkeyPatch,
    target: DeploymentTarget,
    workflow_target: str,
) -> None:
    service = GitHubDeploymentService(
        app_id="123",
        private_key="unused",
        allowed_repositories={"owner/repository"},
    )
    monkeypatch.setattr(service, "_app_jwt", lambda: "app-jwt")
    calls: list[tuple[str, str, dict[str, Any] | None]] = []

    def request(
        method: str,
        path: str,
        *,
        token: str,
        body: dict[str, Any] | None = None,
        allow_not_found: bool = False,
    ) -> dict[str, Any] | None:
        calls.append((method, path, body))
        if path == "/repos/owner/repository/installation":
            return {"id": 7}
        if path == "/app/installations/7/access_tokens":
            return {"token": "installation-token"}
        if path == "/repos/owner/repository":
            return {"default_branch": "main"}
        if method == "POST" and path.endswith("/dispatches"):
            return None
        raise AssertionError(f"Unexpected GitHub request: {method} {path} {token}")

    monkeypatch.setattr(service, "_request", request)
    selection = GitHubDeploymentSelection(
        repository_url="https://github.com/owner/repository",
        source_workflow="orders.yxmd",
        target=target,
        conflict_behavior="Fail",
    )
    result = service.deploy(
        selection=selection,
        workspace_id="workspace-id",
        artifact_path="alteryx-workflows/orders",
    )
    assert result.status == "dispatched"
    assert result.ref == "main"
    assert result.target == target
    assert not any(call[0] == "PUT" for call in calls)
    assert not any("/contents/" in call[1] for call in calls)
    dispatch_call = next(call for call in calls if call[1].endswith("/dispatches"))
    assert dispatch_call[2] is not None
    assert dispatch_call[2]["inputs"]["FABRIC_WORKSPACE_ID"] == "workspace-id"
    assert dispatch_call[2]["inputs"]["workflow_filter"] == "alteryx-workflows/orders"
    assert dispatch_call[2]["inputs"]["target"] == workflow_target


def test_rejects_repository_outside_allowlist() -> None:
    service = GitHubDeploymentService(
        app_id="123",
        private_key="unused",
        allowed_repositories={"approved/repository"},
    )
    selection = GitHubDeploymentSelection(
        repository_url="https://github.com/other/repository",
        source_workflow="orders.yxmd",
        target="notebook",
        workflow_file=APPROVED_WORKFLOW_PATH,
    )
    with pytest.raises(GitHubDeploymentError, match="not in"):
        service.deploy(
            selection=selection,
            workspace_id="workspace-id",
            artifact_path="orders",
        )


def test_uses_explicit_local_github_cli_mode(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("GITHUB_AUTH_MODE", "gh-cli")
    response = subprocess.CompletedProcess(
        ["gh"], 0, stdout="local-token\n", stderr=""
    )
    monkeypatch.setattr(subprocess, "run", lambda *args, **kwargs: response)
    service = GitHubDeploymentService.from_environment()
    assert service.user_token == "local-token"
    assert service.allowed_repositories is None
