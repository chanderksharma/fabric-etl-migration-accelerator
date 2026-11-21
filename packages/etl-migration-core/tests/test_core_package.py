"""Standalone tests for the etl-migration-core PyPI package."""

from __future__ import annotations

from pathlib import Path

import pytest

from etl_migration_core.contracts.ir import IR_VERSION, SourcePlatform
from etl_migration_core.contracts.spi import UnsupportedTargetCapabilityError
from etl_migration_core.intake.discovery import DiscoveryService
from etl_migration_core.sources.defaults import create_default_registry
from etl_migration_core.targets import create_target_registry


def test_core_discovery_and_source_registry() -> None:
    sample_dir = Path(__file__).parents[3] / "alteryx-workflows"
    summary = DiscoveryService().discover(sample_dir)
    assert summary.workflow_count > 0

    registry = create_default_registry(load_entry_points=False)
    ids = [adapter.adapter_id for adapter in registry.adapters]
    assert ids == ["alteryx", "informatica-idmc", "informatica-powercenter"]

    first = summary.workflows[0]
    assert first.source_platform is SourcePlatform.ALTERYX
    detected = registry.detect(Path(first.source_path), first.display_path)
    package = registry.parse(Path(first.source_path), detected.match)
    assert package.ir_version == IR_VERSION
    assert len(package.assets) == 1


def test_core_target_registry_placeholders_fail_closed() -> None:
    registry = create_target_registry(load_entry_points=False)
    info_map = {item.platform_id: item for item in registry.list_providers()}
    assert set(info_map) == {"databricks", "snowflake", "synapse"}
    for pid in ("databricks", "snowflake", "synapse"):
        assert info_map[pid].implemented is False
        with pytest.raises(UnsupportedTargetCapabilityError):
            registry.require_implemented(pid, capability="codegen")
