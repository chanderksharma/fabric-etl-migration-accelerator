"""Bounded IDMC export acquisition tests."""

import io
import json
import zipfile
from dataclasses import dataclass
from pathlib import Path

import pytest

from etl_migration_core.sources.informatica_idmc.export_client import (
    HttpResponse,
    IdmcExportClient,
    IdmcExportError,
)


@dataclass
class FakeTransport:
    responses: list[HttpResponse]

    def __post_init__(self) -> None:
        self.calls: list[tuple[str, str, dict[str, str], bytes | None]] = []

    def request(
        self,
        method: str,
        url: str,
        headers: dict[str, str],
        body: bytes | None = None,
    ) -> HttpResponse:
        self.calls.append((method, url, headers, body))
        return self.responses.pop(0)


def _package_bytes() -> bytes:
    output = io.BytesIO()
    with zipfile.ZipFile(output, "w") as archive:
        archive.writestr("manifest.json", '{"assets":[]}')
    return output.getvalue()


def test_export_client_polls_and_writes_package_atomically(tmp_path: Path) -> None:
    package = _package_bytes()
    transport = FakeTransport(
        [
            HttpResponse(200, {}, b'{"id":"job-1"}'),
            HttpResponse(200, {}, b'{"status":{"state":"IN_PROGRESS"}}'),
            HttpResponse(200, {}, b'{"status":{"state":"SUCCESSFUL"}}'),
            HttpResponse(200, {"Content-Type": "application/zip"}, package),
        ]
    )
    client = IdmcExportClient(
        base_api_url="https://dm.example.com/saas",
        session_id="session-value",
        transport=transport,
        poll_interval_seconds=0,
        max_polls=3,
    )
    destination = tmp_path / "export.zip"

    result = client.export(
        object_ids=("asset-1", "asset-2"),
        destination=destination,
        job_name="etl-assessment",
    )

    assert result.job_id == "job-1"
    assert result.path == destination
    assert result.size_bytes == len(package)
    assert len(result.sha256) == 64
    assert destination.read_bytes() == package
    request = json.loads(transport.calls[0][3] or b"{}")
    assert request["objects"] == [
        {"id": "asset-1", "includeDependencies": True},
        {"id": "asset-2", "includeDependencies": True},
    ]
    assert all(
        call[2]["INFA-SESSION-ID"] == "session-value"
        for call in transport.calls
    )


def test_export_client_surfaces_terminal_failure_without_package_write(
    tmp_path: Path,
) -> None:
    transport = FakeTransport(
        [
            HttpResponse(200, {}, b'{"id":"job-2"}'),
            HttpResponse(
                200,
                {},
                b'{"status":{"state":"FAILED","message":"Dependency unavailable"}}',
            ),
        ]
    )
    destination = tmp_path / "export.zip"
    client = IdmcExportClient(
        base_api_url="https://dm.example.com/saas",
        session_id="session-value",
        transport=transport,
        poll_interval_seconds=0,
        max_polls=2,
    )

    with pytest.raises(IdmcExportError, match="Dependency unavailable"):
        client.export(object_ids=("asset-1",), destination=destination)

    assert not destination.exists()


def test_export_client_rejects_untrusted_url_and_invalid_package(tmp_path: Path) -> None:
    with pytest.raises(ValueError, match="HTTPS"):
        IdmcExportClient(
            base_api_url="http://dm.example.com/saas",
            session_id="session-value",
            transport=FakeTransport([]),
        )
    client = IdmcExportClient(
        base_api_url="https://dm.example.com/saas",
        session_id="session-value",
        transport=FakeTransport(
            [
                HttpResponse(200, {}, b'{"id":"job-3"}'),
                HttpResponse(200, {}, b'{"status":{"state":"SUCCESSFUL"}}'),
                HttpResponse(200, {}, b"not-a-zip"),
            ]
        ),
        poll_interval_seconds=0,
    )

    with pytest.raises(IdmcExportError, match="ZIP"):
        client.export(
            object_ids=("asset-1",),
            destination=tmp_path / "export.zip",
        )


def test_export_client_rejects_invalid_job_id_and_private_hosts(tmp_path: Path) -> None:
    with pytest.raises(ValueError, match="local host"):
        IdmcExportClient(
            base_api_url="https://localhost/saas",
            session_id="session-value",
            transport=FakeTransport([]),
        )
    with pytest.raises(ValueError, match="private or loopback"):
        IdmcExportClient(
            base_api_url="https://169.254.169.254/saas",
            session_id="session-value",
            transport=FakeTransport([]),
        )
    with pytest.raises(ValueError, match="allowlist"):
        IdmcExportClient(
            base_api_url="https://dm.example.com/saas",
            session_id="session-value",
            transport=FakeTransport([]),
            allowed_hosts=("allowed.informaticacloud.com",),
        )

    client = IdmcExportClient(
        base_api_url="https://dm.example.com/saas",
        session_id="session-value",
        transport=FakeTransport([HttpResponse(200, {}, b'{"id":"../admin"}')]),
        poll_interval_seconds=0,
    )
    with pytest.raises(IdmcExportError, match="job ID"):
        client.export(object_ids=("asset-1",), destination=tmp_path / "export.zip")


def test_export_client_rejects_oversized_and_zip_bomb_packages(tmp_path: Path) -> None:
    oversized = _package_bytes()
    client = IdmcExportClient(
        base_api_url="https://dm.example.com/saas",
        session_id="session-value",
        transport=FakeTransport(
            [
                HttpResponse(200, {}, b'{"id":"job-size"}'),
                HttpResponse(200, {}, b'{"status":{"state":"SUCCESSFUL"}}'),
                HttpResponse(200, {"Content-Type": "application/zip"}, oversized),
            ]
        ),
        poll_interval_seconds=0,
        max_package_bytes=16,
    )
    destination = tmp_path / "oversized.zip"
    with pytest.raises(IdmcExportError, match="size limit"):
        client.export(object_ids=("asset-1",), destination=destination)
    assert not destination.exists()

    bomb_buffer = io.BytesIO()
    with zipfile.ZipFile(bomb_buffer, "w", compression=zipfile.ZIP_DEFLATED) as archive:
        archive.writestr("zeros.bin", b"\x00" * (2 * 1024 * 1024))
    bomb_bytes = bomb_buffer.getvalue()
    bomb_client = IdmcExportClient(
        base_api_url="https://dm.example.com/saas",
        session_id="session-value",
        transport=FakeTransport(
            [
                HttpResponse(200, {}, b'{"id":"job-bomb"}'),
                HttpResponse(200, {}, b'{"status":{"state":"SUCCESSFUL"}}'),
                HttpResponse(200, {"Content-Type": "application/zip"}, bomb_bytes),
            ]
        ),
        poll_interval_seconds=0,
        max_uncompressed_bytes=1024 * 1024,
    )
    bomb_dest = tmp_path / "bomb.zip"
    with pytest.raises(IdmcExportError, match="ZIP"):
        bomb_client.export(object_ids=("asset-1",), destination=bomb_dest)
    assert not bomb_dest.exists()


