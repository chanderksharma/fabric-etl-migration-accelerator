"""GitHub App workflow bootstrap and dispatch."""

from __future__ import annotations

import json
import os
import re
import subprocess
import time
import uuid
from pathlib import Path
from typing import Any, Literal
from urllib.error import HTTPError
from urllib.parse import quote, urlparse
from urllib.request import Request, urlopen

import jwt
from pydantic import BaseModel, Field, field_validator

APPROVED_WORKFLOW_PATH = ".github/workflows/deploy-fabric-artifacts.yml"
GITHUB_API_VERSION = "2022-11-28"
REPOSITORY_PATTERN = re.compile(r"^[A-Za-z0-9_.-]+/[A-Za-z0-9_.-]+$")
REF_PATTERN = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._/-]*$")
DeploymentTarget = Literal["notebook", "dataflow", "pipeline", "bundle"]


class GitHubConfigurationError(RuntimeError):
    """Raised when GitHub App configuration is incomplete."""


class GitHubDeploymentError(RuntimeError):
    """Raised when GitHub rejects deployment setup or dispatch."""


class GitHubDeploymentSelection(BaseModel):
    """Validated request from the deployment UI."""

    repository_url: str = Field(min_length=1, max_length=240)
    source_workflow: str = Field(min_length=1, max_length=500)
    target: DeploymentTarget = "notebook"
    workflow_file: str = APPROVED_WORKFLOW_PATH
    ref: str | None = Field(default=None, min_length=1, max_length=120)
    conflict_behavior: Literal["Fail", "Skip", "Update"] = "Fail"

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

    @field_validator("ref")
    @classmethod
    def validate_ref(cls, value: str | None) -> str | None:
        if value is None:
            return None
        if not REF_PATTERN.fullmatch(value) or ".." in value:
            raise ValueError("Git ref contains unsupported characters")
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
            candidate_root = Path(__file__).resolve().parents[3]
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
        self._request(
            "POST",
            f"/repos/{repository}/actions/workflows/{quote(workflow_name, safe='')}/dispatches",
            token=installation_token,
            body={
                "ref": dispatch_ref,
                "inputs": {
                    "deployment_id": deployment_id,
                    "FABRIC_WORKSPACE_ID": workspace_id,
                    "artifact_root": "generated-fabric-workflows",
                    "target": (
                        "DataPipeline"
                        if selection.target == "pipeline"
                        else selection.target.title()
                    ),
                    "workflow_filter": artifact_path,
                    "conflict_behavior": selection.conflict_behavior,
                    "dry_run": False,
                },
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
        data = json.dumps(body).encode("utf-8") if body is not None else None
        request = Request(
            f"{self.api_base}{path}",
            data=data,
            method=method,
            headers={
                "Accept": "application/vnd.github+json",
                "Authorization": f"Bearer {token}",
                "Content-Type": "application/json",
                "User-Agent": "fabric-etl-migration-accelerator",
                "X-GitHub-Api-Version": GITHUB_API_VERSION,
            },
        )
        try:
            with urlopen(request, timeout=20) as response:
                payload = response.read()
        except HTTPError as error:
            payload = error.read()
            message = payload.decode("utf-8", errors="replace")
            raise GitHubDeploymentError(
                f"GitHub API {method} {path} failed ({error.code}): {message}"
            ) from error
        if not payload:
            return None
        parsed = json.loads(payload)
        if not isinstance(parsed, dict):
            raise GitHubDeploymentError("GitHub API returned an unexpected response")
        return parsed
