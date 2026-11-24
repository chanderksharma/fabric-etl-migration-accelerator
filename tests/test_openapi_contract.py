"""OpenAPI schema contract checks guarding backend/frontend API alignment."""

from __future__ import annotations

from accelerator.server.api import app


def test_openapi_exposes_core_and_capability_routes() -> None:
    schema = app.openapi()
    paths = set(schema["paths"])

    expected_paths = {
        "/health",
        "/livez",
        "/readyz",
        "/api/sources",
        "/api/plugins",
        "/api/targets",
        "/api/targets/{platform_id}",
        "/api/runs",
        "/api/runs/{identity}",
        "/api/runs/{identity}/status",
        "/api/runs/{identity}/neutral-assessment",
        "/api/runs/{identity}/targets/{platform_id}/evaluate",
        "/api/runs/{identity}/targets/{platform_id}/generate",
        "/api/runs/{identity}/targets/{platform_id}/capacity",
    }
    assert expected_paths.issubset(paths)
    assert "get" in schema["paths"]["/api/runs"]
    assert "post" in schema["paths"]["/api/runs"]


def test_openapi_component_schemas_match_frontend_contracts() -> None:
    schemas = app.openapi()["components"]["schemas"]

    target_props = set(schemas["TargetDescriptor"]["properties"])
    assert {
        "platform_id",
        "display_name",
        "provider_version",
        "supported_ir_versions",
        "implemented",
        "status",
        "capabilities",
        "target_kinds",
        "origin",
        "description",
    }.issubset(target_props)

    source_props = set(schemas["SourceDescriptor"]["properties"])
    assert {
        "adapter_id",
        "platform",
        "product",
        "origin",
        "supported_extensions",
    }.issubset(source_props)

    run_list_props = set(schemas["RunListResponse"]["properties"])
    assert {"total", "limit", "offset", "runs"}.issubset(run_list_props)

    gen_props = set(schemas["TargetGenerationResult"]["properties"])
    assert {"platform_id", "provider_version", "target_kind", "artifacts"}.issubset(gen_props)
