"""Backward-compatibility contracts for existing Alteryx users."""

from pathlib import Path

from typer.core import TyperGroup
from typer.main import get_command

from accelerator.api import app as api
from accelerator.cli import app as cli
from accelerator.domain import SUPPORTED_EXTENSIONS
from accelerator.runs import _artifact_path
from accelerator.schemas import (
    DiscoverySummaryResponse,
    EstateAssessmentResponse,
    WorkflowAssessmentResponse,
    WorkflowCandidateResponse,
)


def test_legacy_alteryx_extensions_remain_supported() -> None:
    assert {".yxmd", ".yxmc", ".yxwz", ".yxzp"}.issubset(SUPPORTED_EXTENSIONS)


def test_legacy_api_routes_remain_available() -> None:
    routes = {route.path for route in api.routes if hasattr(route, "path")}

    assert {
        "/health",
        "/api/intake/preview",
        "/api/intake/upload",
        "/api/assessment/upload",
        "/api/graph/schema",
        "/api/registry",
        "/api/snapshots/local",
        "/api/snapshots/upload",
        "/api/runs",
        "/api/runs/{identity}",
        "/api/runs/{identity}/cancel",
        "/api/runs/{identity}/generate",
        "/api/runs/{identity}/export",
        "/api/runs/{identity}/candidates",
        "/api/runs/{identity}/bundle",
        "/api/runs/{identity}/evidence",
    }.issubset(routes)


def test_legacy_cli_commands_remain_available() -> None:
    command = get_command(cli)

    assert isinstance(command, TyperGroup)
    assert {"assess", "preview", "serve", "generate"}.issubset(command.commands)


def test_legacy_artifact_paths_remain_stable() -> None:
    assert _artifact_path("orders.yxmd") == Path("orders")
    assert _artifact_path(r"alteryx-workflows\orders.yxmd") == Path(
        "alteryx-workflows",
        "orders",
    )
    assert _artifact_path("estate.zip!folder/orders.yxmd") == Path(
        "estate-zip",
        "folder",
        "orders",
    )


def test_legacy_response_fields_remain_available() -> None:
    candidate_fields = WorkflowCandidateResponse.model_fields
    assessment_fields = WorkflowAssessmentResponse.model_fields
    discovery_fields = DiscoverySummaryResponse.model_fields
    estate_fields = EstateAssessmentResponse.model_fields

    assert {
        "source_path",
        "display_path",
        "extension",
        "size_bytes",
        "sha256",
        "archive_path",
        "archive_chain",
    }.issubset(candidate_fields)
    assert {
        "path",
        "tool_count",
        "connection_count",
        "recommended_target",
        "target_components",
        "unsupported_tools",
        "migration_wave",
        "dependencies",
        "data_sources",
    }.issubset(assessment_fields)
    assert {"workflow_count", "workflows", "skipped"}.issubset(discovery_fields)
    assert {"workflow_count", "assessments", "failures"}.issubset(estate_fields)
