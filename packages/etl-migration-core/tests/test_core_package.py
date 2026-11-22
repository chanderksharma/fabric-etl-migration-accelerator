"""Standalone tests for the etl-migration-core PyPI package."""

from __future__ import annotations

from pathlib import Path
from unittest.mock import mock_open

import pytest

from etl_migration_core.contracts.ir import (
    EXTENSIBLE_SOURCE_IR_VERSION,
    IR_VERSION,
    SourcePlatform,
    is_ir_compatible,
)
from etl_migration_core.contracts.spi import UnsupportedTargetCapabilityError
from etl_migration_core.contracts.testing import assert_source_adapter_conformance
from etl_migration_core.intake.discovery import DiscoveryService
from etl_migration_core.sources.defaults import create_default_registry
from etl_migration_core.sources.io import SourceChangedError, SourceTooLargeError, read_bounded
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


def test_semver_ir_compatibility_and_adapter_conformance() -> None:
    assert is_ir_compatible(IR_VERSION, (IR_VERSION,))
    assert not is_ir_compatible(EXTENSIBLE_SOURCE_IR_VERSION, (IR_VERSION,))
    assert is_ir_compatible(EXTENSIBLE_SOURCE_IR_VERSION, ("1.*",))
    assert is_ir_compatible(EXTENSIBLE_SOURCE_IR_VERSION, ("^1.0.0",))
    assert not is_ir_compatible("2.0.0", ("1.*", "^1.0.0"))

    sample = Path(__file__).parents[3] / "alteryx-workflows" / "sample_alteryx_workflow.yxmd"
    registry = create_default_registry(load_entry_points=False)
    alteryx = next(a for a in registry.adapters if a.adapter_id == "alteryx")
    package = assert_source_adapter_conformance(alteryx, sample)
    assert package.source_platform is SourcePlatform.ALTERYX
    stream_match = registry.detect_bytes(sample.read_bytes(), sample.name)
    assert stream_match.adapter.adapter_id == "alteryx"


def test_read_bounded_sizes_the_read_from_the_file_not_the_limit(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    source = tmp_path / "small.xml"
    source.write_bytes(b"<a/>")
    assert read_bounded(source, 100 * 1024 * 1024) == b"<a/>"

    opened = mock_open(read_data=b"<a/>")
    monkeypatch.setattr(Path, "open", opened)
    read_bounded(source, 100 * 1024 * 1024)
    opened.return_value.read.assert_called_once_with(len(b"<a/>") + 1)


def test_read_bounded_fails_closed_for_oversized_and_growing_files(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    source = tmp_path / "large.xml"
    source.write_bytes(b"x" * 11)
    with pytest.raises(SourceTooLargeError, match="above the 10 byte limit"):
        read_bounded(source, 10)

    class Stat:
        st_size = 3

    monkeypatch.setattr(Path, "stat", lambda _self, **_kwargs: Stat())
    with pytest.raises(SourceChangedError, match="changed while it was being read"):
        read_bounded(source, 100)
