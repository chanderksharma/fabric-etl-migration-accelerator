"""Validated, dispatch-only GitLab CI integration."""

from __future__ import annotations

import os
import re
import uuid
from typing import Any, Literal
from urllib.parse import quote, urlparse

from pydantic import BaseModel, Field, field_validator

from accelerator.delivery.base import (
    REF_PATTERN as REF_PATTERN,
)
from accelerator.delivery.base import (
    USER_AGENT,
    DeploymentConfigurationError,
    DeploymentDispatchError,
    DeploymentSelectionBase,
    format_fabric_target,
    http_json_request,
    validate_publication_dispatch,
)
from accelerator.delivery.base import (
    DeploymentTarget as DeploymentTarget,
)
from accelerator.delivery.provenance import PublicationDispatch

APPROVED_CI_FILE = ".gitlab-ci.yml"
PROJECT_PART_PATTERN = re.compile(r"^[A-Za-z0-9_.-]+$")


class GitLabConfigurationError(DeploymentConfigurationError):
    """Raised when server-side GitLab configuration is incomplete."""


class GitLabDeploymentError(DeploymentDispatchError):
    """Raised when GitLab rejects project validation or pipeline dispatch."""


class GitLabDeploymentSelection(DeploymentSelectionBase):
    """Validated request from the deployment UI."""

    project_url: str = Field(min_length=1, max_length=500)
    ci_file: str = APPROVED_CI_FILE

    @field_validator("project_url")
    @classmethod
    def validate_project_url(cls, value: str) -> str:
        parse_gitlab_project(value)
        return value

    @field_validator("ci_file")
    @classmethod
    def validate_ci_file(cls, value: str) -> str:
        if value != APPROVED_CI_FILE:
            raise ValueError(f"Only {APPROVED_CI_FILE} is approved")
        return value


class GitLabDeploymentResult(BaseModel):
    """Accepted GitLab CI pipeline dispatch."""

    deployment_id: str
    project: str
    ci_file: str
    ref: str
    target: DeploymentTarget
    pipeline_url: str
    status: Literal["dispatched"] = "dispatched"


def parse_gitlab_project(project_url: str) -> tuple[str, str]:
    """Return the HTTPS origin and namespaced project path."""
    parsed = urlparse(project_url)
    if (
        parsed.scheme != "https"
        or not parsed.hostname
        or parsed.username
        or parsed.password
        or parsed.query
        or parsed.fragment
    ):
        raise ValueError("Use an HTTPS GitLab project URL")
    parts = [
        part
        for part in parsed.path.removesuffix("/").removesuffix(".git").split("/")
        if part
    ]
    if len(parts) < 2 or any(
        part == "-" or not PROJECT_PART_PATTERN.fullmatch(part) for part in parts
    ):
        raise ValueError("GitLab project path must include a valid namespace and project")
    origin = f"{parsed.scheme}://{parsed.netloc}"
    return origin, "/".join(parts)


class GitLabDeploymentService:
    """Validate one GitLab project and dispatch its existing CI pipeline."""

    provider_id = "gitlab"

    def __init__(
        self,
        *,
        token: str,
        allowed_projects: set[str],
        web_base: str = "https://gitlab.com",
    ) -> None:
        parsed = urlparse(web_base.rstrip("/"))
        if (
            parsed.scheme != "https"
            or not parsed.hostname
            or parsed.path not in {"", "/"}
            or parsed.query
            or parsed.fragment
        ):
            raise GitLabConfigurationError(
                "GITLAB_BASE_URL must be an HTTPS GitLab origin"
            )
        if not token:
            raise GitLabConfigurationError("GITLAB_TOKEN is required")
        if not allowed_projects:
            raise GitLabConfigurationError("GITLAB_ALLOWED_PROJECTS is required")
        self.token = token
        self.allowed_projects = {value.casefold() for value in allowed_projects}
        self.web_base = f"{parsed.scheme}://{parsed.netloc}".rstrip("/")
        self.api_base = f"{self.web_base}/api/v4"

    @classmethod
    def from_environment(cls) -> GitLabDeploymentService:
        """Create a service from server-only environment variables."""
        token = os.getenv("GITLAB_TOKEN", "").strip()
        projects = {
            value.strip()
            for value in os.getenv("GITLAB_ALLOWED_PROJECTS", "").split(",")
            if value.strip()
        }
        return cls(
            token=token,
            allowed_projects=projects,
            web_base=os.getenv("GITLAB_BASE_URL", "https://gitlab.com").strip(),
        )

    def deploy(
        self,
        *,
        selection: GitLabDeploymentSelection,
        workspace_id: str,
        artifact_path: str,
        publication: PublicationDispatch | None = None,
    ) -> GitLabDeploymentResult:
        """Dispatch one existing GitLab CI pipeline."""
        origin, project = parse_gitlab_project(selection.project_url)
        if origin.casefold() != self.web_base.casefold():
            raise GitLabDeploymentError(
                "GitLab project URL does not match GITLAB_BASE_URL"
            )
        if project.casefold() not in self.allowed_projects:
            raise GitLabDeploymentError("Project is not in GITLAB_ALLOWED_PROJECTS")
        if not workspace_id:
            raise GitLabConfigurationError("ACCELERATOR_DEV_WORKSPACE is not configured")

        encoded_project = quote(project, safe="")
        metadata = self._request("GET", f"/projects/{encoded_project}")
        project_id = metadata.get("id")
        canonical_project = metadata.get("path_with_namespace")
        default_branch = metadata.get("default_branch")
        if not isinstance(project_id, (int, str)) or not str(project_id):
            raise GitLabDeploymentError("GitLab project ID was not returned")
        if (
            not isinstance(canonical_project, str)
            or canonical_project.casefold() != project.casefold()
        ):
            raise GitLabDeploymentError("GitLab project identity did not match")
        if not isinstance(default_branch, str) or not default_branch:
            raise GitLabDeploymentError("GitLab default branch was not returned")
        dispatch_ref = selection.ref or default_branch

        encoded_file = quote(APPROVED_CI_FILE, safe="")
        encoded_ref = quote(dispatch_ref, safe="")
        self._request(
            "GET",
            f"/projects/{project_id}/repository/files/{encoded_file}?ref={encoded_ref}",
        )

        correlation_id = uuid.uuid4().hex
        variables = [
            {"key": "FABRIC_OPERATION", "value": "Deploy"},
            {"key": "DEPLOYMENT_ID", "value": correlation_id},
            {"key": "FABRIC_WORKSPACE_ID", "value": workspace_id},
            {
                "key": "ARTIFACT_ROOT",
                "value": (
                    publication.artifact_root if publication else "generated-fabric-workflows"
                ),
            },
            {
                "key": "TARGET",
                "value": format_fabric_target(selection.target),
            },
            {"key": "WORKFLOW_FILTER", "value": artifact_path},
            {"key": "CONFLICT_BEHAVIOR", "value": selection.conflict_behavior},
            {"key": "DRY_RUN", "value": "false"},
        ]
        if selection.expected_commit is not None:
            variables.append({"key": "FABRIC_EXPECTED_COMMIT", "value": selection.expected_commit})
        validate_publication_dispatch(
            publication,
            publication_digest=selection.publication_digest,
            expected_commit=selection.expected_commit,
            error_cls=GitLabDeploymentError,
        )
        if publication is not None:
            variables.append(
                {"key": "FABRIC_PUBLICATION_MANIFEST_SHA256", "value": publication.manifest_sha256}
            )
        response = self._request(
            "POST",
            f"/projects/{project_id}/pipeline",
            body={
                "ref": dispatch_ref,
                "variables": variables,
            },
        )
        pipeline_id = response.get("id")
        pipeline_url = response.get("web_url")
        if not isinstance(pipeline_id, (int, str)) or not str(pipeline_id):
            raise GitLabDeploymentError("GitLab pipeline ID was not returned")
        if not isinstance(pipeline_url, str) or not pipeline_url:
            raise GitLabDeploymentError("GitLab pipeline URL was not returned")
        return GitLabDeploymentResult(
            deployment_id=str(pipeline_id),
            project=canonical_project,
            ci_file=APPROVED_CI_FILE,
            ref=dispatch_ref,
            target=selection.target,
            pipeline_url=pipeline_url,
        )

    def _request(
        self,
        method: str,
        path: str,
        *,
        body: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        parsed = http_json_request(
            provider_label="GitLab",
            api_base=self.api_base,
            method=method,
            path=path,
            headers={
                "Accept": "application/json",
                "Content-Type": "application/json",
                "PRIVATE-TOKEN": self.token,
                "User-Agent": USER_AGENT,
            },
            body=body,
            allow_empty=False,
            error_cls=GitLabDeploymentError,
        )
        assert parsed is not None
        return parsed
