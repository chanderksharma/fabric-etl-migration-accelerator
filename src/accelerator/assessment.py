"""Deterministic Alteryx workflow assessment."""

from __future__ import annotations

from collections import Counter
from dataclasses import dataclass
from pathlib import Path

from accelerator.capacity import CapacityStaticProfile, build_capacity_profile
from accelerator.effort import assessment_effort_days
from accelerator.etl_ir import AssetType, SourcePlatform
from accelerator.graph import GRAPH_VERSION
from accelerator.graph import WorkflowParseError as WorkflowParseError
from accelerator.sources.alteryx import AlteryxSourceAdapter

DATAFLOW_TOOL_MARKERS = frozenset(
    {
        "alteryxselect",
        "appendfields",
        "autofield",
        "crosstab",
        "datetime",
        "dbfileinput",
        "dbfileoutput",
        "inputdata",
        "outputdata",
        "select",
        "filter",
        "formula",
        "join",
        "union",
        "sort",
        "summarize",
        "sample",
        "unique",
        "recordid",
        "regex",
        "textinput",
        "transpose",
    }
)
NOTEBOOK_TOOL_MARKERS = frozenset({"python", "rtool", "spatial", "predictive", "multirowformula"})
PIPELINE_TOOL_MARKERS = frozenset(
    {"download", "dynamicinput", "runcommand", "email", "detour", "controlcontainer"}
)
NEUTRAL_TOOL_MARKERS = frozenset({"toolcontainer", "comment", "explorerbox", "browse"})
REGISTRY_VERSION = "2026.11.3"
RULES_VERSION = "1.4.0"
ANNOTATION_IDENTITIES = frozenset(
    {
        "AlteryxGuiToolkit.ToolContainer.ToolContainer",
        "AlteryxGuiToolkit.TextBox.TextBox",
        "AlteryxGuiToolkit.Questions.Tab.Tab",
        "AlteryxGuiToolkit.Questions.Label.Label",
        "AlteryxGuiToolkit.Questions.LabelGroup.LabelGroup",
    }
)


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


def assess_workflow(path: Path) -> WorkflowAssessment:
    """Parse and assess one XML-based Alteryx workflow."""
    graph = AlteryxSourceAdapter().legacy_graph(path)
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
    score = _complexity_score(len(tool_names), connection_count, inventory)
    band = "Low" if score < 20 else "Medium" if score < 40 else "High"
    target, components, reason = _recommend_target(inventory, unsupported)
    migration_wave = _migration_wave(target, band)
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
        migration_wave=migration_wave,
        estimated_effort_days=effort_days,
        registry_version=REGISTRY_VERSION,
        rules_version=RULES_VERSION,
        dependencies=graph.dependencies,
        data_sources=graph.data_sources,
        capacity_profile=build_capacity_profile(path),
    )


def _support_for(plugin: str) -> str:
    if plugin in ANNOTATION_IDENTITIES:
        return "neutral"
    pieces = plugin.casefold().split(".")
    if len(pieces) != 3 or pieces[0] != "alteryxbasepluginsgui" or pieces[1] != pieces[2]:
        return "manual"
    normalized = pieces[2].removesuffix("tool")
    if normalized in NEUTRAL_TOOL_MARKERS:
        return "neutral"
    if normalized in PIPELINE_TOOL_MARKERS:
        return "pipeline"
    if normalized in NOTEBOOK_TOOL_MARKERS:
        return "notebook"
    if normalized in DATAFLOW_TOOL_MARKERS:
        return "dataflow"
    return "manual"


def _complexity_score(
    tool_count: int,
    connection_count: int,
    inventory: tuple[ToolInventoryItem, ...],
) -> int:
    manual_count = sum(item.count for item in inventory if item.support == "manual")
    notebook_count = sum(item.count for item in inventory if item.support == "notebook")
    pipeline_count = sum(item.count for item in inventory if item.support == "pipeline")
    neutral_count = sum(item.count for item in inventory if item.support == "neutral")
    return (
        tool_count
        - neutral_count
        + connection_count
        + manual_count * 5
        + notebook_count * 2
        + pipeline_count
    )


def _recommend_target(
    inventory: tuple[ToolInventoryItem, ...],
    unsupported: tuple[str, ...],
) -> tuple[str, tuple[str, ...], str]:
    support_types = {item.support for item in inventory}
    components = tuple(
        component
        for support, component in (
            ("dataflow", "Dataflow Gen2"),
            ("notebook", "Fabric Notebook"),
            ("pipeline", "Fabric Pipeline"),
        )
        if support in support_types
    )
    if not components:
        return (
            "Manual rework",
            (),
            f"{len(unsupported)} tool type(s) have no deterministic mapping",
        )
    target = components[0] if len(components) == 1 else "Mixed Fabric solution"
    reason = (
        f"Deterministic mappings require {', '.join(components)}"
        if len(components) > 1
        else f"Detected tools map to {components[0]}"
    )
    if unsupported:
        reason += f"; {len(unsupported)} unsupported tool type(s) require manual redesign"
    return target, components, reason


def _migration_wave(target: str, complexity_band: str) -> str:
    if target == "Manual rework":
        return "Redesign"
    if target == "Mixed Fabric solution" or complexity_band == "High":
        return "Pilot"
    if complexity_band == "Medium":
        return "Wave 2"
    return "Wave 1"


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
