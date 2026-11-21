"""Tests for GitLab CI pipeline dispatch."""

from typing import Any

import pytest

from accelerator.delivery.gitlab import (
    APPROVED_CI_FILE,
    DeploymentTarget,
    GitLabDeploymentError,
    GitLabDeploymentSelection,
    GitLabDeploymentService,
    parse_gitlab_project,
)


def test_gitlab_project_url_validation() -> None:
    assert parse_gitlab_project(
        "https://gitlab.com/group/subgroup/project.git"
    ) == ("https://gitlab.com", "group/subgroup/project")
    assert parse_gitlab_project(
        "https://gitlab.example.com/group/project"
    ) == ("https://gitlab.example.com", "group/project")
    with pytest.raises(ValueError, match="HTTPS GitLab"):
        parse_gitlab_project("group/project")
    with pytest.raises(ValueError, match="GitLab project path"):
        parse_gitlab_project("https://gitlab.com/project")


@pytest.mark.parametrize(
    ("target", "pipeline_target"),
    [("dataflow", "Dataflow"), ("pipeline", "DataPipeline")],
)
def test_dispatches_existing_gitlab_pipeline(
    monkeypatch: pytest.MonkeyPatch,
    target: DeploymentTarget,
    pipeline_target: str,
) -> None:
    service = GitLabDeploymentService(
        token="project-token",
        allowed_projects={"group/subgroup/project"},
        web_base="https://gitlab.com",
    )
    calls: list[tuple[str, str, dict[str, Any] | None]] = []

    def request(
        method: str,
        path: str,
        *,
        body: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        calls.append((method, path, body))
        if path == "/projects/group%2Fsubgroup%2Fproject":
            return {
                "id": 42,
                "path_with_namespace": "group/subgroup/project",
                "default_branch": "main",
            }
        if path == "/projects/42/repository/files/.gitlab-ci.yml?ref=main":
            return {"file_path": ".gitlab-ci.yml"}
        if method == "POST" and path == "/projects/42/pipeline":
            return {
                "id": 901,
                "ref": "main",
                "status": "created",
                "web_url": "https://gitlab.com/group/subgroup/project/-/pipelines/901",
            }
        raise AssertionError(f"Unexpected GitLab request: {method} {path}")

    monkeypatch.setattr(service, "_request", request)
    selection = GitLabDeploymentSelection(
        project_url="https://gitlab.com/group/subgroup/project",
        source_workflow="orders.yxmd",
        target=target,
        conflict_behavior="Update",
    )

    result = service.deploy(
        selection=selection,
        workspace_id="workspace-id",
        artifact_path="alteryx-workflows/orders",
    )

    assert result.status == "dispatched"
    assert result.deployment_id == "901"
    assert result.ref == "main"
    assert result.pipeline_url.endswith("/pipelines/901")
    pipeline_call = next(call for call in calls if call[1] == "/projects/42/pipeline")
    assert pipeline_call[2] is not None
    variables = {
        variable["key"]: variable["value"]
        for variable in pipeline_call[2]["variables"]
    }
    assert variables["FABRIC_OPERATION"] == "Deploy"
    assert variables["FABRIC_WORKSPACE_ID"] == "workspace-id"
    assert variables["WORKFLOW_FILTER"] == "alteryx-workflows/orders"
    assert variables["TARGET"] == pipeline_target
    assert variables["CONFLICT_BEHAVIOR"] == "Update"
    assert variables["DRY_RUN"] == "false"


def test_gitlab_accepts_pipeline_deployment_target() -> None:
    selection = GitLabDeploymentSelection(
        project_url="https://gitlab.com/group/project",
        source_workflow="tf_orders",
        target="pipeline",
    )

    assert selection.target == "pipeline"


def test_gitlab_rejects_project_outside_allowlist() -> None:
    service = GitLabDeploymentService(
        token="project-token",
        allowed_projects={"approved/project"},
        web_base="https://gitlab.com",
    )
    selection = GitLabDeploymentSelection(
        project_url="https://gitlab.com/other/project",
        source_workflow="orders.yxmd",
        target="notebook",
        ci_file=APPROVED_CI_FILE,
    )

    with pytest.raises(GitLabDeploymentError, match="not in"):
        service.deploy(
            selection=selection,
            workspace_id="workspace-id",
            artifact_path="orders",
        )


def test_gitlab_rejects_project_from_another_host() -> None:
    service = GitLabDeploymentService(
        token="project-token",
        allowed_projects={"group/project"},
        web_base="https://gitlab.example.com",
    )
    selection = GitLabDeploymentSelection(
        project_url="https://gitlab.com/group/project",
        source_workflow="orders.yxmd",
        target="dataflow",
    )

    with pytest.raises(GitLabDeploymentError, match="GITLAB_BASE_URL"):
        service.deploy(
            selection=selection,
            workspace_id="workspace-id",
            artifact_path="orders",
        )


def test_gitlab_service_reads_server_only_environment(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("GITLAB_BASE_URL", "https://gitlab.example.com")
    monkeypatch.setenv("GITLAB_TOKEN", "server-token")
    monkeypatch.setenv(
        "GITLAB_ALLOWED_PROJECTS",
        "group/project,group/subgroup/another",
    )

    service = GitLabDeploymentService.from_environment()

    assert service.web_base == "https://gitlab.example.com"
    assert service.allowed_projects == {
        "group/project",
        "group/subgroup/another",
    }
