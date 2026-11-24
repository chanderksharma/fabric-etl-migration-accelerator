"""Shared CI/CD deployment dispatcher contracts, validation models, and HTTP client."""

from __future__ import annotations

import json
import re
from typing import Any, Literal, Protocol, Self, runtime_checkable
from urllib.error import HTTPError, URLError
from urllib.request import Request, urlopen

from pydantic import BaseModel, Field, field_validator, model_validator

from accelerator.delivery.provenance import PublicationDispatch

DeploymentTarget = Literal["notebook", "dataflow", "pipeline", "bundle"]
REF_PATTERN = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._/-]*$")
USER_AGENT = "fabric-etl-migration-accelerator"


class DeploymentConfigurationError(RuntimeError):
    """Raised when server-side CI/CD dispatcher configuration is incomplete."""


class DeploymentDispatchError(RuntimeError):
    """Raised when a remote CI/CD provider rejects validation or dispatch."""


class DeploymentSelectionBase(BaseModel):
    """Common validated dispatch parameters shared across CI/CD providers."""

    source_workflow: str = Field(min_length=1, max_length=500)
    target: DeploymentTarget = "notebook"
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

    @field_validator("ref")
    @classmethod
    def validate_ref(cls, value: str | None) -> str | None:
        if value is None:
            return None
        if not REF_PATTERN.fullmatch(value) or ".." in value:
            raise ValueError("Git ref contains unsupported characters")
        return value


def format_fabric_target(target: DeploymentTarget) -> str:
    """Format an internal deployment target name for CI workflow inputs."""
    return "DataPipeline" if target == "pipeline" else target.title()


def validate_publication_dispatch(
    publication: PublicationDispatch | None,
    *,
    publication_digest: str | None,
    expected_commit: str | None,
    error_cls: type[DeploymentDispatchError],
) -> None:
    """Ensure publication provenance inputs are mutually consistent before dispatch."""
    if publication is not None:
        if publication_digest is None or expected_commit is None:
            raise error_cls("Publication dispatch requires a digest and commit")
        if not publication.artifact_root.endswith(f"/{publication_digest}"):
            raise error_cls("Publication path does not match the selected digest")
    elif publication_digest is not None:
        raise error_cls("Publication dispatch is missing verified provenance")


def http_json_request(
    *,
    provider_label: str,
    api_base: str,
    method: str,
    path: str,
    headers: dict[str, str],
    body: dict[str, Any] | None = None,
    allow_empty: bool = False,
    timeout_seconds: int = 20,
    error_cls: type[DeploymentDispatchError] = DeploymentDispatchError,
) -> dict[str, Any] | None:
    """Execute one bounded JSON HTTPS request against a CI/CD provider API."""
    data = json.dumps(body).encode("utf-8") if body is not None else None
    request = Request(
        f"{api_base}{path}",
        data=data,
        method=method,
        headers=headers,
    )
    try:
        with urlopen(request, timeout=timeout_seconds) as response:
            payload = response.read()
    except HTTPError as error:
        payload = error.read()
        message = payload.decode("utf-8", errors="replace")
        raise error_cls(
            f"{provider_label} API {method} {path} failed ({error.code}): {message}"
        ) from error
    except URLError as error:
        raise error_cls(
            f"{provider_label} API {method} {path} failed: {error.reason}"
        ) from error
    if not payload:
        if allow_empty:
            return None
        raise error_cls(f"{provider_label} API returned an empty response")
    parsed = json.loads(payload)
    if not isinstance(parsed, dict):
        raise error_cls(f"{provider_label} API returned an unexpected response")
    return parsed


@runtime_checkable
class CiDeploymentDispatcher(Protocol):
    """Pluggable contract implemented by CI/CD deployment dispatchers."""

    provider_id: str

    def deploy(
        self,
        *,
        selection: Any,
        workspace_id: str,
        artifact_path: str,
        publication: PublicationDispatch | None = None,
    ) -> BaseModel: ...
