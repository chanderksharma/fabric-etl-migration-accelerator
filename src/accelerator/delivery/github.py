"""GitHub App workflow bootstrap and dispatch."""

from __future__ import annotations

import os
import re
import subprocess
import time
import uuid
from pathlib import Path
from typing import Any, Literal
from urllib.parse import quote, urlparse

import jwt
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

APPROVED_WORKFLOW_PATH = ".github/workflows/deploy-fabric-artifacts.yml"
GITHUB_API_VERSION = "2022-11-28"
REPOSITORY_PATTERN = re.compile(r"^[A-Za-z0-9_.-]+/[A-Za-z0-9_.-]+$")


class GitHubConfigurationError(DeploymentConfigurationError):
    """Raised when GitHub App configuration is incomplete."""


class GitHubDeploymentError(DeploymentDispatchError):
    """Raised when GitHub rejects deployment setup or dispatch."""


class GitHubDeploymentSelection(DeploymentSelectionBase):
    """Validated request from the deployment UI."""

    repository_url: str = Field(min_length=1, max_length=240)
    workflow_file: str = APPROVED_WORKFLOW_PATH

    @field_validator("repository_url")
    @classmethod
    def validate_repository_url(cls, value: str) -> str:
        parse_github_repository(value)
        return value

    @field_validator("workflow_file")
    @classmethod
    def validate_workflow_file(cls, value: str) -> str:
        if value != APPROVED_WORKFLOW_PATH:
            raise ValueError(f"Only {APPROVED_WORKFLOW_PATH} is approved")
        return value


class GitHubDeploymentResult(BaseModel):
    """Accepted GitHub Actions deployment dispatch."""

    deployment_id: str
    repository: str
    workflow_file: str
    ref: str
    target: DeploymentTarget
    status: Literal["dispatched"] = "dispatched"


def parse_github_repository(repository_url: str) -> str:
    """Return owner/repository for a supported GitHub URL."""
    parsed = urlparse(repository_url)
    parts = [part for part in parsed.path.removesuffix(".git").split("/") if part]
    if parsed.scheme != "https" or parsed.hostname != "github.com" or len(parts) != 2:
        raise ValueError("Use an HTTPS GitHub repository URL")
    repository = "/".join(parts)
    if not REPOSITORY_PATTERN.fullmatch(repository):
        raise ValueError("GitHub repository owner or name contains unsupported characters")
    return repository


class GitHubDeploymentService:
    """Create an approved workflow when absent and dispatch it."""

    provider_id = "github"

    def __init__(
        self,
        *,
        app_id: str | None = None,
        private_key: str | None = None,
        user_token: str | None = None,
        allowed_repositories: set[str] | None = None,
        api_base: str = "https://api.github.com",
    ) -> None:
        self.app_id = app_id
        self.private_key = private_key
        self.user_token = user_token
        self.allowed_repositories = (
            {value.casefold() for value in allowed_repositories}
            if allowed_repositories is not None
            else None
        )
        self.api_base = api_base.rstrip("/")
        if not user_token and not (app_id and private_key):
            raise GitHubConfigurationError("A GitHub App or user token is required")

    @classmethod
    def from_environment(cls) -> GitHubDeploymentService:
        """Create a service from server-only environment variables."""
        auth_mode = os.getenv("GITHUB_AUTH_MODE", "github-app").strip().casefold()
        if auth_mode == "gh-cli":
            parents = Path(__file__).resolve().parents
            candidate_root = parents[3] if len(parents) > 3 else Path.cwd()
            repository_root = (
                candidate_root if (candidate_root / ".git").exists() else Path.cwd()
            )
            try:
                token_result = subprocess.run(
                    ["gh", "auth", "token"],
                    cwd=repository_root,
                    capture_output=True,
                    text=True,
                    check=True,
                    timeout=10,
                )
            except FileNotFoundError as error:
                raise GitHubConfigurationError("GitHub CLI is not installed") from error
            except subprocess.TimeoutExpired as error:
                raise GitHubConfigurationError(
                    "GitHub CLI authentication check timed out"
                ) from error
            except subprocess.CalledProcessError as error:
                detail = error.stderr.strip() or "GitHub CLI authentication failed"
                raise GitHubConfigurationError(detail) from error
            token = token_result.stdout.strip()
            if not token:
                raise GitHubConfigurationError("GitHub CLI did not return a token")
            return cls(user_token=token)
        if auth_mode != "github-app":
            raise GitHubConfigurationError("GITHUB_AUTH_MODE must be github-app or gh-cli")

        app_id = os.getenv("GITHUB_APP_ID", "").strip()
        inline_key = os.getenv("GITHUB_APP_PRIVATE_KEY", "").replace("\\n", "\n").strip()
        key_path = os.getenv("GITHUB_APP_PRIVATE_KEY_PATH", "").strip()
        repositories = {
            value.strip()
            for value in os.getenv("GITHUB_ALLOWED_REPOSITORIES", "").split(",")
            if value.strip()
        }
        if key_path:
            path = Path(key_path).expanduser().resolve()
            if not path.is_file():
                raise GitHubConfigurationError("GITHUB_APP_PRIVATE_KEY_PATH is not a file")
            inline_key = path.read_text(encoding="utf-8").strip()
        missing = [
            name
            for name, value in (
                ("GITHUB_APP_ID", app_id),
                ("GitHub App private key", inline_key),
                ("GITHUB_ALLOWED_REPOSITORIES", repositories),
            )
            if not value
        ]
        if missing:
            raise GitHubConfigurationError(
                f"GitHub deployment is not configured: {', '.join(missing)}"
            )
        return cls(
            app_id=app_id,
            private_key=inline_key,
            allowed_repositories=repositories,
        )

    def deploy(
        self,
        *,
        selection: GitHubDeploymentSelection,
        workspace_id: str,
        artifact_path: str,
        publication: PublicationDispatch | None = None,
    ) -> GitHubDeploymentResult:
        """Dispatch one existing deployment workflow."""
        repository = parse_github_repository(selection.repository_url)
        if (
            self.allowed_repositories is not None
            and repository.casefold() not in self.allowed_repositories
        ):
            raise GitHubDeploymentError("Repository is not in GITHUB_ALLOWED_REPOSITORIES")
        if not workspace_id:
            raise GitHubConfigurationError("ACCELERATOR_DEV_WORKSPACE is not configured")

        installation_token: str
        if self.user_token:
            installation_token = self.user_token
        else:
            app_token = self._app_jwt()
            installation = self._request(
                "GET", f"/repos/{repository}/installation", token=app_token
            )
            installation_id = installation.get("id") if installation else None
            if not isinstance(installation_id, int):
                raise GitHubDeploymentError("GitHub App installation was not found")
            token_response = self._request(
                "POST",
                f"/app/installations/{installation_id}/access_tokens",
                token=app_token,
                body={},
            )
            token_value = token_response.get("token") if token_response else None
            if not isinstance(token_value, str) or not token_value:
                raise GitHubDeploymentError("GitHub App installation token was not returned")
            installation_token = token_value

        metadata = self._request("GET", f"/repos/{repository}", token=installation_token)
        default_branch = metadata.get("default_branch") if metadata else None
        if not isinstance(default_branch, str) or not default_branch:
            raise GitHubDeploymentError("Repository default branch was not returned")
        dispatch_ref = selection.ref or default_branch

        workflow_name = Path(APPROVED_WORKFLOW_PATH).name
        deployment_id = uuid.uuid4().hex
        inputs: dict[str, Any] = {
            "deployment_id": deployment_id,
            "FABRIC_WORKSPACE_ID": workspace_id,
            "artifact_root": "generated-fabric-workflows",
            "target": format_fabric_target(selection.target),
            "workflow_filter": artifact_path,
            "conflict_behavior": selection.conflict_behavior,
            "dry_run": False,
        }
        if selection.expected_commit is not None:
            inputs["expected_commit"] = selection.expected_commit
        validate_publication_dispatch(
            publication,
            publication_digest=selection.publication_digest,
            expected_commit=selection.expected_commit,
            error_cls=GitHubDeploymentError,
        )
        if publication is not None:
            inputs["artifact_root"] = publication.artifact_root
            inputs["publication_manifest_sha256"] = publication.manifest_sha256
        self._request(
            "POST",
            f"/repos/{repository}/actions/workflows/{quote(workflow_name, safe='')}/dispatches",
            token=installation_token,
            body={
                "ref": dispatch_ref,
                "inputs": inputs,
            },
        )
        return GitHubDeploymentResult(
            deployment_id=deployment_id,
            repository=repository,
            workflow_file=APPROVED_WORKFLOW_PATH,
            ref=dispatch_ref,
            target=selection.target,
        )

    def _app_jwt(self) -> str:
        if not self.app_id or not self.private_key:
            raise GitHubConfigurationError("GitHub App credentials are not configured")
        now = int(time.time())
        encoded = jwt.encode(
            {"iat": now - 60, "exp": now + 540, "iss": self.app_id},
            self.private_key,
            algorithm="RS256",
        )
        return str(encoded)

    def _request(
        self,
        method: str,
        path: str,
        *,
        token: str,
        body: dict[str, Any] | None = None,
    ) -> dict[str, Any] | None:
        return http_json_request(
            provider_label="GitHub",
            api_base=self.api_base,
            method=method,
            path=path,
            headers={
                "Accept": "application/vnd.github+json",
                "Authorization": f"Bearer {token}",
                "Content-Type": "application/json",
                "User-Agent": USER_AGENT,
                "X-GitHub-Api-Version": GITHUB_API_VERSION,
            },
            body=body,
            allow_empty=True,
            error_cls=GitHubDeploymentError,
        )
