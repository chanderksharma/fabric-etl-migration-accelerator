"""Deterministic Alteryx workflow assessment."""

from __future__ import annotations

from collections import Counter
from dataclasses import dataclass
from pathlib import Path

from etl_migration_core.contracts.ir import AssetType, SourcePlatform
from etl_migration_core.planning.effort import assessment_effort_days
from etl_migration_core.sources.alteryx import AlteryxSourceAdapter
from etl_migration_core.sources.alteryx.graph import GRAPH_VERSION, WorkflowGraph
from etl_migration_core.sources.alteryx.graph import WorkflowParseError as WorkflowParseError
from etl_target_fabric.assessment.support_matrix import (
    ANNOTATION_IDENTITIES as ANNOTATION_IDENTITIES,
)
from etl_target_fabric.assessment.support_matrix import (
    DATAFLOW_TOOL_MARKERS as DATAFLOW_TOOL_MARKERS,
)
from etl_target_fabric.assessment.support_matrix import (
    NEUTRAL_TOOL_MARKERS as NEUTRAL_TOOL_MARKERS,
)
from etl_target_fabric.assessment.support_matrix import (
    NOTEBOOK_TOOL_MARKERS as NOTEBOOK_TOOL_MARKERS,
)
from etl_target_fabric.assessment.support_matrix import (
    PIPELINE_TOOL_MARKERS as PIPELINE_TOOL_MARKERS,
)
from etl_target_fabric.assessment.support_matrix import (
    REGISTRY_VERSION as REGISTRY_VERSION,
)
from etl_target_fabric.assessment.support_matrix import (
    RULES_VERSION as RULES_VERSION,
)
from etl_target_fabric.assessment.support_matrix import (
    alteryx_support_for as _support_for,
)
from etl_target_fabric.assessment.support_matrix import (
    complexity_band,
    complexity_score,
    migration_wave,
    recommend_target,
)
from etl_target_fabric.capacity.model import CapacityStaticProfile, build_capacity_profile


@dataclass(frozen=True, slots=True)
class ToolInventoryItem:
    """Count of one Alteryx tool type."""

    name: str
    count: int
    support: str


@dataclass(frozen=True, slots=True)
class WorkflowAssessment:
    """Deterministic static assessment of one workflow."""

    path: str
    tool_count: int
    connection_count: int
    tools: tuple[ToolInventoryItem, ...]
    complexity_score: int
    complexity_band: str
    recommended_target: str
    target_components: tuple[str, ...]
    recommendation_reason: str
    unsupported_tools: tuple[str, ...]
    migration_wave: str
    estimated_effort_days: float
    registry_version: str
    rules_version: str
    dependencies: tuple[str, ...] = ()
    data_sources: tuple[str, ...] = ()
    graph_schema_version: str = GRAPH_VERSION
    source_platform: SourcePlatform = SourcePlatform.ALTERYX
    source_product: str = "Alteryx Designer"
    asset_type: AssetType = AssetType.WORKFLOW
    native_id: str | None = None
    folder: str | None = None
    capacity_profile: CapacityStaticProfile | None = None


def assess_workflow(
    path: Path, *, graph: WorkflowGraph | None = None
) -> WorkflowAssessment:
    """Parse and assess one XML-based Alteryx workflow."""
    graph = graph or AlteryxSourceAdapter().legacy_graph(path)
    active = [node for node in graph.nodes if not node.disabled]
    tool_names = [node.name for node in active]
    counts = Counter((node.name, node.plugin) for node in active)
    inventory = tuple(
        ToolInventoryItem(name=name, count=count, support=_support_for(plugin))
        for (name, plugin), count in sorted(counts.items())
    )
    active_ids = {node.id for node in active}
    connection_count = sum(
        source in active_ids and target in active_ids for source, target, _ in graph.edges
    )
    unsupported = tuple(item.name for item in inventory if item.support == "manual")
    score = complexity_score(
        [(item.support, item.count) for item in inventory],
        connection_count,
    )
    band = complexity_band(score)
    target, components, reason = recommend_target(
        {item.support for item in inventory},
        len(unsupported),
        item_noun="tool",
    )
    wave = migration_wave(target, band)
    effort_days = _estimated_effort_days(inventory)
    return WorkflowAssessment(
        path=path.name,
        tool_count=len(tool_names),
        connection_count=connection_count,
        tools=inventory,
        complexity_score=score,
        complexity_band=band,
        recommended_target=target,
        target_components=components,
        recommendation_reason=reason,
        unsupported_tools=unsupported,
        migration_wave=wave,
        estimated_effort_days=effort_days,
        registry_version=REGISTRY_VERSION,
        rules_version=RULES_VERSION,
        dependencies=graph.dependencies,
        data_sources=graph.data_sources,
        capacity_profile=build_capacity_profile(path, graph=graph),
    )


def _estimated_effort_days(
    inventory: tuple[ToolInventoryItem, ...],
) -> float:
    manual_count = sum(item.count for item in inventory if item.support == "manual")
    return assessment_effort_days(unsupported_component_count=manual_count)


def registry_entries() -> list[dict[str, str]]:
    """Expose the same explicit mapping data used by assessment."""
    groups = {
        "dataflow": DATAFLOW_TOOL_MARKERS,
        "notebook": NOTEBOOK_TOOL_MARKERS,
        "pipeline": PIPELINE_TOOL_MARKERS,
        "neutral": NEUTRAL_TOOL_MARKERS,
    }
    entries = [
        {
            "identity": f"alteryxbasepluginsgui.{name}.{name}",
            "support": support,
            "compiler": "review subset only"
            if name
            in {
                "inputdata",
                "dbfileinput",
                "textinput",
                "filter",
                "select",
                "alteryxselect",
                "outputdata",
                "dbfileoutput",
                "browse",
            }
            else "not implemented",
            "notes": "Recommendation is not proof of executable conversion",
        }
        for support, names in groups.items()
        for name in sorted(names)
    ]
    entries.extend(
        {
            "identity": identity,
            "support": "neutral",
            "compiler": "context only",
            "notes": "Non-executable canvas annotation",
        }
        for identity in sorted(ANNOTATION_IDENTITIES)
    )
    return entries
