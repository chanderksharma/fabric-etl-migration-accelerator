"""Source adapter registration and dispatch contracts."""

from dataclasses import dataclass
from pathlib import Path

import pytest

from etl_migration_core.contracts.ir import EtlPackage, SourcePlatform
from etl_migration_core.sources.base import SourceMatch
from etl_migration_core.sources.defaults import create_default_registry
from etl_migration_core.sources.registry import (
    AmbiguousSourceFormatError,
    SourceAdapterRegistry,
    UnknownSourceFormatError,
)


@dataclass(frozen=True)
class FakeAdapter:
    adapter_id: str
    platform: SourcePlatform
    product: str
    confidence: int
    marker: bytes
    adapter_version: str = "1.0"
    parser_version: str = "1.0"
    registry_version: str = "1.0"
    rules_version: str = "1.0"

    def probe(self, path: Path, display_path: str) -> SourceMatch | None:
        if self.marker not in path.read_bytes():
            return None
        return SourceMatch(
            adapter_id=self.adapter_id,
            platform=self.platform,
            product=self.product,
            asset_type="workflow",
            confidence=self.confidence,
            display_path=display_path,
        )

    def parse(self, path: Path, match: SourceMatch) -> EtlPackage:
        return EtlPackage(
            source_platform=self.platform,
            source_product=self.product,
            export_id=match.display_path,
        )


def test_registry_selects_highest_confidence_adapter(tmp_path: Path) -> None:
    source = tmp_path / "workflow.xml"
    source.write_bytes(b"POWERMART")
    registry = SourceAdapterRegistry(
        (
            FakeAdapter(
                "generic-xml",
                SourcePlatform.ALTERYX,
                "Generic XML",
                20,
                b"POWER",
            ),
            FakeAdapter(
                "powercenter",
                SourcePlatform.INFORMATICA_POWERCENTER,
                "PowerCenter",
                100,
                b"POWERMART",
            ),
        )
    )

    detected = registry.detect(source, "workflow.xml")

    assert detected.match.adapter_id == "powercenter"
    assert detected.adapter.platform is SourcePlatform.INFORMATICA_POWERCENTER
    assert registry.parse(source, detected.match).source_product == "PowerCenter"


def test_registry_rejects_unknown_and_ambiguous_formats(tmp_path: Path) -> None:
    source = tmp_path / "workflow.bin"
    source.write_bytes(b"same")
    unknown = SourceAdapterRegistry(
        (
            FakeAdapter(
                "powercenter",
                SourcePlatform.INFORMATICA_POWERCENTER,
                "PowerCenter",
                100,
                b"POWERMART",
            ),
        )
    )
    with pytest.raises(UnknownSourceFormatError, match=r"workflow\.bin"):
        unknown.detect(source, "workflow.bin")

    ambiguous = SourceAdapterRegistry(
        (
            FakeAdapter(
                "first",
                SourcePlatform.INFORMATICA_POWERCENTER,
                "PowerCenter",
                100,
                b"same",
            ),
            FakeAdapter(
                "second",
                SourcePlatform.INFORMATICA_IDMC,
                "IDMC",
                100,
                b"same",
            ),
        )
    )
    with pytest.raises(AmbiguousSourceFormatError, match=r"first, second"):
        ambiguous.detect(source, "workflow.bin")


def test_registry_rejects_duplicate_adapter_ids() -> None:
    adapter = FakeAdapter(
        "duplicate",
        SourcePlatform.ALTERYX,
        "Alteryx",
        100,
        b"AlteryxDocument",
    )

    with pytest.raises(ValueError, match="duplicate source adapter"):
        SourceAdapterRegistry((adapter, adapter))


def test_default_registry_contains_all_source_platforms() -> None:
    registry = create_default_registry()

    assert {
        adapter.platform for adapter in registry.adapters
    } == set(SourcePlatform)

