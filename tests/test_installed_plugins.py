"""Prove the packaging path with the example plugins installed as real distributions.

The rest of the suite loads the examples from their source files. These tests run only where
both example distributions are installed (the ``plugin-entry-points`` CI job runs
``uv pip install ./examples/plugins/...``) and cover distribution metadata, entry-point
discovery, the run service, and the ``tool plugins`` command.
"""

from __future__ import annotations

import json
import os
from importlib import metadata
from pathlib import Path

import pytest
from typer.testing import CliRunner

from accelerator.cli.app import app as cli_app
from accelerator.runtime.runs import RunService
from accelerator.targets import create_default_target_registry
from etl_migration_core.sources.defaults import create_default_registry

SOURCE_DISTRIBUTION = "etl-source-ssis-example"
TARGET_DISTRIBUTION = "etl-target-databricks-example"
REQUIRE_ENV = "ACCELERATOR_REQUIRE_INSTALLED_PLUGINS"
SSIS_FIXTURE = (
    Path(__file__).parents[1]
    / "examples"
    / "plugins"
    / "synthetic-ssis"
    / "fixtures"
    / "synthetic-package.dtsx"
)


def _installed(name: str) -> bool:
    try:
        metadata.distribution(name)
    except metadata.PackageNotFoundError:
        return False
    return True


def _example_plugins_installed() -> bool:
    installed = _installed(SOURCE_DISTRIBUTION) and _installed(TARGET_DISTRIBUTION)
    if not installed and os.environ.get(REQUIRE_ENV) == "1":
        raise RuntimeError(f"{REQUIRE_ENV}=1 but the example plugin distributions are missing")
    return installed


pytestmark = pytest.mark.skipif(
    not _example_plugins_installed(), reason="example plugin distributions are not installed"
)


def _canonical(name: str | None) -> str:
    return (name or "").replace("_", "-").lower()


def test_installed_plugins_are_discovered_through_entry_points() -> None:
    sources = create_default_registry(plugin_errors="raise")
    targets = create_default_target_registry(plugin_errors="raise")

    assert sources.origin_of("alteryx") == "builtin"
    assert sources.origin_of("synthetic-ssis") == "plugin:synthetic-ssis"
    assert targets.origin_of("databricks") == "plugin:synthetic-databricks"
    loaded = {
        (result.group, result.name): result
        for result in (*sources.plugin_results, *targets.plugin_results)
        if result.status == "loaded"
    }
    ssis = loaded[("etl_migration.sources", "synthetic-ssis")]
    databricks = loaded[("etl_migration.targets", "synthetic-databricks")]
    assert _canonical(ssis.distribution) == SOURCE_DISTRIBUTION
    assert _canonical(databricks.distribution) == TARGET_DISTRIBUTION


def test_installed_source_plugin_drives_a_local_run(tmp_path: Path) -> None:
    with RunService(tmp_path / "state") as service:
        preview = service.preview(SSIS_FIXTURE)
        assert preview.workflows[0].source_platform == "ssis"
        run = service.create_run(preview.snapshot_id)
        service.execute(run.id)
        neutral = service.get_neutral_assessment(run.id)

    assert neutral.assessments[0].unknown_components == ["ssis_unverified_task"]


def test_plugins_command_reports_the_installed_distributions() -> None:
    result = CliRunner().invoke(cli_app, ["plugins"])

    assert result.exit_code == 0, result.output
    catalog = json.loads(result.stdout)
    assert catalog["failed_count"] == 0
    assert {item["adapter_id"] for item in catalog["sources"]} >= {"alteryx", "synthetic-ssis"}
    assert {item["platform_id"] for item in catalog["targets"]} >= {"fabric", "databricks"}
    distributions = {
        _canonical(item["distribution"])
        for item in catalog["plugins"]
        if item["status"] == "loaded"
    }
    assert {SOURCE_DISTRIBUTION, TARGET_DISTRIBUTION} <= distributions
