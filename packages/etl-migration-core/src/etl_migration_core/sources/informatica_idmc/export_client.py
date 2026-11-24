"""Bounded server-side acquisition of IDMC export packages."""

from __future__ import annotations

import hashlib
import ipaddress
import json
import re
import time
import uuid
import zipfile
from collections.abc import Collection
from dataclasses import dataclass
from pathlib import Path
from typing import Protocol, runtime_checkable
from urllib.error import HTTPError, URLError
from urllib.parse import quote, urlparse
from urllib.request import Request, urlopen

_CHUNK_BYTES = 1024 * 1024
_JOB_ID_PATTERN = re.compile(r"^[A-Za-z0-9._-]{1,128}$")
_MAX_ZIP_ENTRIES = 10_000
_MAX_ZIP_COMPRESSION_RATIO = 100
_DEFAULT_MAX_PACKAGE_BYTES = 2 * 1024 * 1024 * 1024
_DEFAULT_MAX_UNCOMPRESSED_BYTES = 4 * 1024 * 1024 * 1024


class IdmcExportError(RuntimeError):
    """Raised when an IDMC export job or package is invalid."""


@dataclass(frozen=True, slots=True)
class HttpResponse:
    """Minimal transport response used by the export client."""

    status: int
    headers: dict[str, str]
    body: bytes


@dataclass(frozen=True, slots=True)
class StreamedFileResponse:
    """Bounded streaming download response written directly to disk."""

    status: int
    headers: dict[str, str]
    size_bytes: int
    sha256: str
    error_body: bytes = b""


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


@runtime_checkable
class StreamingHttpTransport(Protocol):
    """Optional streaming transport avoiding full-package RAM buffering."""

    def download_to_path(
        self,
        url: str,
        headers: dict[str, str],
        destination: Path,
        *,
        max_bytes: int,
    ) -> StreamedFileResponse:
        """Stream one HTTP GET response to disk while enforcing ``max_bytes``."""


@dataclass(frozen=True, slots=True)
class IdmcExportResult:
    """Persisted export package metadata."""

    job_id: str
    path: Path
    size_bytes: int
    sha256: str


def _read_bounded_stream(stream: object, max_bytes: int) -> bytes:
    """Read at most ``max_bytes`` from a file-like response object."""
    reader = getattr(stream, "read", None)
    if not callable(reader):
        raise IdmcExportError("IDMC HTTP stream is not readable")
    chunks: list[bytes] = []
    total = 0
    while True:
        chunk = reader(min(_CHUNK_BYTES, max_bytes - total + 1))
        if not chunk:
            break
        if not isinstance(chunk, (bytes, bytearray)):
            raise IdmcExportError("IDMC HTTP stream returned non-bytes data")
        total += len(chunk)
        if total > max_bytes:
            raise IdmcExportError("IDMC export package exceeds the configured size limit")
        chunks.append(bytes(chunk))
    return b"".join(chunks)


class UrllibTransport:
    """Standard-library IDMC transport with explicit timeouts and bounded reads."""

    def __init__(
        self,
        timeout_seconds: int = 30,
        *,
        max_response_bytes: int = _DEFAULT_MAX_PACKAGE_BYTES,
    ) -> None:
        self.timeout_seconds = timeout_seconds
        self.max_response_bytes = max_response_bytes

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
                    headers=dict(response.headers.items()),
                    body=_read_bounded_stream(response, self.max_response_bytes),
                )
        except HTTPError as error:
            return HttpResponse(
                status=error.code,
                headers=dict(error.headers.items()),
                body=error.read(64 * 1024),
            )
        except URLError as error:
            raise IdmcExportError(f"IDMC request failed: {error.reason}") from error

    def download_to_path(
        self,
        url: str,
        headers: dict[str, str],
        destination: Path,
        *,
        max_bytes: int,
    ) -> StreamedFileResponse:
        request = Request(url, method="GET", headers=headers)
        try:
            with urlopen(request, timeout=self.timeout_seconds) as response:
                digest = hashlib.sha256()
                total = 0
                with destination.open("wb") as target:
                    while True:
                        chunk = response.read(min(_CHUNK_BYTES, max_bytes - total + 1))
                        if not chunk:
                            break
                        total += len(chunk)
                        if total > max_bytes:
                            raise IdmcExportError(
                                "IDMC export package exceeds the configured size limit"
                            )
                        target.write(chunk)
                        digest.update(chunk)
                return StreamedFileResponse(
                    status=response.status,
                    headers=dict(response.headers.items()),
                    size_bytes=total,
                    sha256=digest.hexdigest(),
                )
        except HTTPError as error:
            return StreamedFileResponse(
                status=error.code,
                headers=dict(error.headers.items()),
                size_bytes=0,
                sha256="",
                error_body=error.read(64 * 1024),
            )
        except URLError as error:
            raise IdmcExportError(f"IDMC request failed: {error.reason}") from error


def _validate_base_host(hostname: str, allowed_hosts: Collection[str] | None) -> None:
    normalized = hostname.strip().casefold()
    if allowed_hosts is not None:
        allowed = {host.strip().casefold() for host in allowed_hosts if host.strip()}
        if normalized not in allowed:
            raise ValueError("IDMC base API host is not in the configured allowlist")
        return
    if normalized in {"localhost", "localhost.localdomain"}:
        raise ValueError("IDMC base API URL cannot target a local host")
    try:
        address = ipaddress.ip_address(normalized)
    except ValueError:
        return
    if (
        address.is_loopback
        or address.is_private
        or address.is_link_local
        or address.is_reserved
        or address.is_unspecified
    ):
        raise ValueError("IDMC base API URL cannot target a private or loopback IP address")


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
        max_package_bytes: int = _DEFAULT_MAX_PACKAGE_BYTES,
        max_uncompressed_bytes: int = _DEFAULT_MAX_UNCOMPRESSED_BYTES,
        max_zip_entries: int = _MAX_ZIP_ENTRIES,
        max_compression_ratio: int = _MAX_ZIP_COMPRESSION_RATIO,
        allowed_hosts: Collection[str] | None = None,
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
        _validate_base_host(parsed.hostname, allowed_hosts)
        if not session_id:
            raise ValueError("IDMC session ID is required")
        if max_polls < 1:
            raise ValueError("IDMC max polls must be positive")
        if max_package_bytes < 1:
            raise ValueError("IDMC package size limit must be positive")
        if max_uncompressed_bytes < 1:
            raise ValueError("IDMC uncompressed size limit must be positive")
        if max_zip_entries < 1:
            raise ValueError("IDMC ZIP entry limit must be positive")
        if max_compression_ratio < 1:
            raise ValueError("IDMC ZIP compression ratio limit must be positive")
        self.base_api_url = base_api_url.rstrip("/")
        self._session_id = session_id
        self._transport = transport or UrllibTransport(max_response_bytes=max_package_bytes)
        self._poll_interval_seconds = max(0, poll_interval_seconds)
        self._max_polls = max_polls
        self._max_package_bytes = max_package_bytes
        self._max_uncompressed_bytes = max_uncompressed_bytes
        self._max_zip_entries = max_zip_entries
        self._max_compression_ratio = max_compression_ratio

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
        if not isinstance(job_id, str) or not _JOB_ID_PATTERN.fullmatch(job_id):
            raise IdmcExportError("IDMC export job ID was not returned or is invalid")
        encoded_job_id = quote(job_id, safe="")

        for attempt in range(self._max_polls):
            status = self._json_request(
                "GET",
                f"/public/core/v3/export/{encoded_job_id}",
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

        destination.parent.mkdir(parents=True, exist_ok=True)
        temporary = destination.with_name(
            f".{destination.name}.{uuid.uuid4().hex}.tmp"
        )
        package_path = f"/public/core/v3/export/{encoded_job_id}/package"
        try:
            size_bytes, digest = self._download_package(package_path, temporary)
            if not _valid_zip_file(
                temporary,
                max_entries=self._max_zip_entries,
                max_uncompressed_bytes=self._max_uncompressed_bytes,
                max_compression_ratio=self._max_compression_ratio,
            ):
                raise IdmcExportError("IDMC export package is not a valid or safe ZIP archive")
            temporary.replace(destination)
        finally:
            temporary.unlink(missing_ok=True)
        return IdmcExportResult(
            job_id=job_id,
            path=destination,
            size_bytes=size_bytes,
            sha256=digest,
        )

    def _download_package(self, path: str, temporary: Path) -> tuple[int, str]:
        headers = self._headers(accept="application/zip")
        if isinstance(self._transport, StreamingHttpTransport):
            streamed = self._transport.download_to_path(
                f"{self.base_api_url}{path}",
                headers,
                temporary,
                max_bytes=self._max_package_bytes,
            )
            if not 200 <= streamed.status < 300:
                detail = streamed.error_body.decode("utf-8", errors="replace")[:2000]
                raise IdmcExportError(
                    f"IDMC API GET {path} failed ({streamed.status}): {detail}"
                )
            return streamed.size_bytes, streamed.sha256
        package = self._request("GET", path, accept="application/zip")
        if len(package.body) > self._max_package_bytes:
            raise IdmcExportError("IDMC export package exceeds the configured size limit")
        temporary.write_bytes(package.body)
        return len(package.body), hashlib.sha256(package.body).hexdigest()

    def _headers(self, *, accept: str) -> dict[str, str]:
        return {
            "Accept": accept,
            "Content-Type": "application/json",
            "INFA-SESSION-ID": self._session_id,
            "User-Agent": "etl-fabric-accelerator",
        }

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
            self._headers(accept=accept),
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


def _valid_zip_file(
    path: Path,
    *,
    max_entries: int,
    max_uncompressed_bytes: int,
    max_compression_ratio: int,
) -> bool:
    try:
        with zipfile.ZipFile(path) as archive:
            infos = archive.infolist()
            if len(infos) > max_entries:
                return False
            total_uncompressed = 0
            for info in infos:
                if info.file_size < 0 or info.compress_size < 0:
                    return False
                if (
                    info.compress_size > 0
                    and info.file_size > info.compress_size * max_compression_ratio
                    and info.file_size > _CHUNK_BYTES
                ):
                    return False
                with archive.open(info, "r") as member:
                    member_bytes = 0
                    while chunk := member.read(_CHUNK_BYTES):
                        member_bytes += len(chunk)
                        total_uncompressed += len(chunk)
                        if total_uncompressed > max_uncompressed_bytes:
                            return False
                        if (
                            info.compress_size > 0
                            and member_bytes > info.compress_size * max_compression_ratio
                            and member_bytes > _CHUNK_BYTES
                        ):
                            return False
            return True
    except (zipfile.BadZipFile, RuntimeError, OSError):
        return False

