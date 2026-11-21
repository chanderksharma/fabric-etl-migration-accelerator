"""Bounded server-side acquisition of IDMC export packages."""

from __future__ import annotations

import hashlib
import io
import json
import time
import uuid
import zipfile
from dataclasses import dataclass
from pathlib import Path
from typing import Protocol
from urllib.error import HTTPError, URLError
from urllib.parse import urlparse
from urllib.request import Request, urlopen


class IdmcExportError(RuntimeError):
    """Raised when an IDMC export job or package is invalid."""


@dataclass(frozen=True, slots=True)
class HttpResponse:
    """Minimal transport response used by the export client."""

    status: int
    headers: dict[str, str]
    body: bytes


class HttpTransport(Protocol):
    """Injectable HTTP transport for IDMC API calls."""

    def request(
        self,
        method: str,
        url: str,
        headers: dict[str, str],
        body: bytes | None = None,
    ) -> HttpResponse:
        """Execute one bounded HTTP request."""


@dataclass(frozen=True, slots=True)
class IdmcExportResult:
    """Persisted export package metadata."""

    job_id: str
    path: Path
    size_bytes: int
    sha256: str


class UrllibTransport:
    """Standard-library IDMC transport with explicit timeouts."""

    def __init__(self, timeout_seconds: int = 30) -> None:
        self.timeout_seconds = timeout_seconds

    def request(
        self,
        method: str,
        url: str,
        headers: dict[str, str],
        body: bytes | None = None,
    ) -> HttpResponse:
        request = Request(url, data=body, method=method, headers=headers)
        try:
            with urlopen(request, timeout=self.timeout_seconds) as response:
                return HttpResponse(
                    status=response.status,
                    headers={key: value for key, value in response.headers.items()},
                    body=response.read(),
                )
        except HTTPError as error:
            return HttpResponse(
                status=error.code,
                headers={key: value for key, value in error.headers.items()},
                body=error.read(),
            )
        except URLError as error:
            raise IdmcExportError(f"IDMC request failed: {error.reason}") from error


class IdmcExportClient:
    """Start, poll, download, and persist one IDMC export job."""

    def __init__(
        self,
        *,
        base_api_url: str,
        session_id: str,
        transport: HttpTransport | None = None,
        poll_interval_seconds: float = 2,
        max_polls: int = 60,
        max_package_bytes: int = 2 * 1024 * 1024 * 1024,
    ) -> None:
        parsed = urlparse(base_api_url.rstrip("/"))
        if (
            parsed.scheme != "https"
            or not parsed.hostname
            or parsed.username
            or parsed.password
            or parsed.query
            or parsed.fragment
        ):
            raise ValueError("IDMC base API URL must be an HTTPS URL without credentials")
        if not session_id:
            raise ValueError("IDMC session ID is required")
        if max_polls < 1:
            raise ValueError("IDMC max polls must be positive")
        if max_package_bytes < 1:
            raise ValueError("IDMC package size limit must be positive")
        self.base_api_url = base_api_url.rstrip("/")
        self._session_id = session_id
        self._transport = transport or UrllibTransport()
        self._poll_interval_seconds = max(0, poll_interval_seconds)
        self._max_polls = max_polls
        self._max_package_bytes = max_package_bytes

    def export(
        self,
        *,
        object_ids: tuple[str, ...],
        destination: Path,
        job_name: str | None = None,
    ) -> IdmcExportResult:
        """Export up to 1000 IDMC objects and atomically persist the ZIP."""
        objects = tuple(dict.fromkeys(value.strip() for value in object_ids if value.strip()))
        if not objects:
            raise ValueError("At least one IDMC object ID is required")
        if len(objects) > 1000:
            raise ValueError("IDMC export supports at most 1000 objects per job")
        payload: dict[str, object] = {
            "objects": [
                {"id": identity, "includeDependencies": True}
                for identity in objects
            ]
        }
        if job_name:
            payload["name"] = job_name[:256]
        start = self._json_request(
            "POST",
            "/public/core/v3/export",
            json.dumps(payload).encode("utf-8"),
        )
        job_id = start.get("id")
        if not isinstance(job_id, str) or not job_id:
            raise IdmcExportError("IDMC export job ID was not returned")

        for attempt in range(self._max_polls):
            status = self._json_request(
                "GET",
                f"/public/core/v3/export/{job_id}",
            )
            status_value = status.get("status")
            status_record = status_value if isinstance(status_value, dict) else {}
            state = _normalized_state(status_record.get("state"))
            message = status_record.get("message")
            if state in {"SUCCESS", "SUCCESSFUL"}:
                break
            if state in {"FAILED", "CANCELLED", "CANCELED", "ERROR"}:
                detail = message if isinstance(message, str) and message else state
                raise IdmcExportError(f"IDMC export {job_id} failed: {detail}")
            if attempt + 1 == self._max_polls:
                raise IdmcExportError(
                    f"IDMC export {job_id} did not complete after {self._max_polls} polls"
                )
            if self._poll_interval_seconds:
                time.sleep(self._poll_interval_seconds)

        package = self._request(
            "GET",
            f"/public/core/v3/export/{job_id}/package",
            accept="application/zip",
        )
        if len(package.body) > self._max_package_bytes:
            raise IdmcExportError("IDMC export package exceeds the configured size limit")
        if not _valid_zip(package.body):
            raise IdmcExportError("IDMC export package is not a valid ZIP archive")
        destination.parent.mkdir(parents=True, exist_ok=True)
        temporary = destination.with_name(
            f".{destination.name}.{uuid.uuid4().hex}.tmp"
        )
        try:
            temporary.write_bytes(package.body)
            temporary.replace(destination)
        finally:
            temporary.unlink(missing_ok=True)
        return IdmcExportResult(
            job_id=job_id,
            path=destination,
            size_bytes=len(package.body),
            sha256=hashlib.sha256(package.body).hexdigest(),
        )

    def _json_request(
        self,
        method: str,
        path: str,
        body: bytes | None = None,
    ) -> dict[str, object]:
        response = self._request(method, path, body)
        try:
            parsed = json.loads(response.body.decode("utf-8"))
        except (UnicodeDecodeError, json.JSONDecodeError) as error:
            raise IdmcExportError("IDMC API returned invalid JSON") from error
        if not isinstance(parsed, dict):
            raise IdmcExportError("IDMC API returned an unexpected response")
        return parsed

    def _request(
        self,
        method: str,
        path: str,
        body: bytes | None = None,
        *,
        accept: str = "application/json",
    ) -> HttpResponse:
        response = self._transport.request(
            method,
            f"{self.base_api_url}{path}",
            {
                "Accept": accept,
                "Content-Type": "application/json",
                "INFA-SESSION-ID": self._session_id,
                "User-Agent": "etl-fabric-accelerator",
            },
            body,
        )
        if not 200 <= response.status < 300:
            detail = response.body.decode("utf-8", errors="replace")[:2000]
            raise IdmcExportError(
                f"IDMC API {method} {path} failed ({response.status}): {detail}"
            )
        return response


def _normalized_state(value: object) -> str:
    if not isinstance(value, str):
        return ""
    return value.strip().replace(" ", "_").upper()


def _valid_zip(content: bytes) -> bool:
    try:
        with zipfile.ZipFile(io.BytesIO(content)) as archive:
            return archive.testzip() is None
    except zipfile.BadZipFile:
        return False

