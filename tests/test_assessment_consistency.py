"""Contracts that keep the neutral and Fabric operation facts from drifting apart."""

from __future__ import annotations

from pathlib import Path

import pytest

from etl_migration_core.contracts.operations import (
    HEAVY_OPERATIONS,
    NEUTRAL_OPERATIONS,
    ORCHESTRATION_OPERATIONS,
    TABULAR_OPERATIONS,
    classify_operation_category,
)
from etl_portfolio_assessment.assessment.engine import assess_package_neutral
from etl_target_fabric.assessment import support_matrix as fabric
from etl_target_fabric.assessment.support_matrix import SUPPORT_TABLE_FINGERPRINT

# Operations the neutral engine recognizes but the Fabric compiler cannot translate.
# This is a reviewed list: remove entries as coverage grows, and justify any addition.
KNOWN_FABRIC_COVERAGE_GAPS = frozenset({"merge", "rtool"})

FABRIC_COMPONENT_TABLES = {
    "dataflow": (fabric.DATAFLOW_OPERATIONS, fabric.DATAFLOW_TOOL_MARKERS, "tabular"),
    "notebook": (fabric.NOTEBOOK_OPERATIONS, fabric.NOTEBOOK_TOOL_MARKERS, "script"),
    "pipeline": (fabric.PIPELINE_OPERATIONS, fabric.PIPELINE_TOOL_MARKERS, "orchestration"),
    "neutral": (fabric.NEUTRAL_OPERATIONS, fabric.NEUTRAL_TOOL_MARKERS, "neutral"),
}


@pytest.mark.parametrize("component", FABRIC_COMPONENT_TABLES)
def test_every_fabric_supported_operation_has_the_matching_neutral_category(
    component: str,
) -> None:
    operations, tools, category = FABRIC_COMPONENT_TABLES[component]

    drift = {
        name: classify_operation_category(name)
        for name in sorted(operations | tools)
        if classify_operation_category(name) != category
    }

    assert drift == {}, f"Fabric {component} support disagrees with the neutral tables"


def test_neutral_operations_without_fabric_coverage_are_a_reviewed_list() -> None:
    neutral_known = (
        TABULAR_OPERATIONS | HEAVY_OPERATIONS | ORCHESTRATION_OPERATIONS | NEUTRAL_OPERATIONS
    )

    uncovered = {
        name
        for name in neutral_known
        if classify_operation_category(name) != "neutral"
        and fabric.etl_support_for(name) == "manual"
        and fabric.alteryx_support_for(f"AlteryxBasePluginsGui.{name}.{name}") == "manual"
    }

    assert uncovered == KNOWN_FABRIC_COVERAGE_GAPS


def test_support_table_fingerprint_is_a_golden_value() -> None:
    # Any edit to a Fabric support table changes this value and every Fabric cache key.
    # Update the literal in the same change, together with RULES_VERSION where behavior moves.
    assert SUPPORT_TABLE_FINGERPRINT[:12] == "6e563f36791c"


def test_annotation_tools_do_not_add_neutral_complexity() -> None:
    from etl_migration_core.sources.alteryx import AlteryxSourceAdapter

    sample = (
        Path(__file__).parents[1] / "alteryx-workflows" / "sample_container_sequence.yxmd"
    )
    adapter = AlteryxSourceAdapter()
    match = adapter.probe(sample, sample.name)
    assert match is not None
    package = adapter.parse(sample, match)

    inventory = assess_package_neutral(package)[0].inventory
    containers = [item for item in inventory if item.operation == "toolcontainer"]

    assert containers
    assert {item.classification for item in containers} == {"neutral"}
