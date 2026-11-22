"""Validated, dispatch-only GitLab CI integration."""

from __future__ import annotations

import json
import os
import re
import uuid
from typing import Any, Literal, Self
from urllib.error import HTTPError, URLError
from urllib.parse import quote, urlparse
from urllib.request import Request, urlopen

from pydantic import BaseModel, Field, field_validator, model_validator

from accelerator.delivery.provenance import PublicationDispatch

APPROVED_CI_FILE = ".gitlab-ci.yml"
PROJECT_PART_PATTERN = re.compile(r"^[A-Za-z0-9_.-]+$")
REF_PATTERN = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._/-]*$")
DeploymentTarget = Literal["notebook", "dataflow", "pipeline", "bundle"]


class GitLabConfigurationError(RuntimeError):
    """Raised when server-side GitLab configuration is incomplete."""


class GitLabDeploymentError(RuntimeError):
    """Raised when GitLab rejects project validation or pipeline dispatch."""


class GitLabDeploymentSelection(BaseModel):
    """Validated request from the deployment UI."""

    project_url: str = Field(min_length=1, max_length=500)
    source_workflow: str = Field(min_length=1, max_length=500)
    target: DeploymentTarget = "notebook"
    ci_file: str = APPROVED_CI_FILE
    ref: str | None = Field(default=None, min_length=1, max_length=120)
    expected_commit: str | None = Field(
        default=None, min_length=40, max_length=40, pattern=r"^[0-9a-f]{40}$"
    )
    isolate_local_artifacts: bool = False
    publication_digest: str | None = Field(
        default=None, min_length=64, max_length=64, pattern=r"^[0-9a-f]{64}$"
    )
    conflict_behavior: Literal["Fail", "Skip", "Update"] = "Fail"

    @model_validator(mode="after")
    def validate_publication_revision(self) -> Self:
        if self.publication_digest is not None and self.expected_commit is None:
            raise ValueError("A publication digest requires an expected commit")
        return self

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

    @field_validator("ref")
    @classmethod
    def validate_ref(cls, value: str | None) -> str | None:
        if value is None:
            return None
        if not REF_PATTERN.fullmatch(value) or ".." in value:
            raise ValueError("Git ref contains unsupported characters")
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
                "value": (
                    "DataPipeline"
                    if selection.target == "pipeline"
                    else selection.target.title()
                ),
            },
            {"key": "WORKFLOW_FILTER", "value": artifact_path},
            {"key": "CONFLICT_BEHAVIOR", "value": selection.conflict_behavior},
            {"key": "DRY_RUN", "value": "false"},
        ]
        if selection.expected_commit is not None:
            variables.append({"key": "FABRIC_EXPECTED_COMMIT", "value": selection.expected_commit})
        if publication is not None:
            if selection.publication_digest is None or selection.expected_commit is None:
                raise GitLabDeploymentError("Publication dispatch requires a digest and commit")
            if not publication.artifact_root.endswith(f"/{selection.publication_digest}"):
                raise GitLabDeploymentError("Publication path does not match the selected digest")
            variables.append(
                {"key": "FABRIC_PUBLICATION_MANIFEST_SHA256", "value": publication.manifest_sha256}
            )
        elif selection.publication_digest is not None:
            raise GitLabDeploymentError("Publication dispatch is missing verified provenance")
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
        data = json.dumps(body).encode("utf-8") if body is not None else None
        request = Request(
            f"{self.api_base}{path}",
            data=data,
            method=method,
            headers={
                "Accept": "application/json",
                "Content-Type": "application/json",
                "PRIVATE-TOKEN": self.token,
                "User-Agent": "fabric-etl-migration-accelerator",
            },
        )
        try:
            with urlopen(request, timeout=20) as response:
                payload = response.read()
        except HTTPError as error:
            payload = error.read()
            message = payload.decode("utf-8", errors="replace")
            raise GitLabDeploymentError(
                f"GitLab API {method} {path} failed ({error.code}): {message}"
            ) from error
        except URLError as error:
            raise GitLabDeploymentError(
                f"GitLab API {method} {path} failed: {error.reason}"
            ) from error
        if not payload:
            raise GitLabDeploymentError("GitLab API returned an empty response")
        parsed = json.loads(payload)
        if not isinstance(parsed, dict):
            raise GitLabDeploymentError("GitLab API returned an unexpected response")
        return parsed
