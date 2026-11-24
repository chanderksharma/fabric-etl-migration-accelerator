"""Microsoft Fabric target-support classifications for source tools and IR ops."""

from __future__ import annotations

import hashlib
import json

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

ASSESSMENT_RULES_VERSION = "1.4.1"
DATAFLOW_OPERATIONS = frozenset(
    {
        "aggregator",
        "expression",
        "filter",
        "joiner",
        "lookup",
        "router",
        "sequence_generator",
        "sorter",
        "source",
        "source_qualifier",
        "target",
        "union",
        "update_strategy",
        "xml_source_qualifier",
    }
)
NOTEBOOK_OPERATIONS = frozenset(
    {
        "advanced",
        "custom_transformation",
        "java",
        "python",
        "script",
    }
)
PIPELINE_OPERATIONS = frozenset(
    {
        "assignment",
        "command",
        "decision",
        "email",
        "mapping_task",
        "mappingtask",
        "session",
        "taskflow",
        "workflow",
        "worklet",
    }
)
NEUTRAL_OPERATIONS = frozenset({"annotation", "container", "end", "start"})


def support_table_fingerprint() -> str:
    """Hash every support table so an edit invalidates caches even without a version bump."""
    payload = {
        name: sorted(table)
        for name, table in {
            "dataflow_tools": DATAFLOW_TOOL_MARKERS,
            "notebook_tools": NOTEBOOK_TOOL_MARKERS,
            "pipeline_tools": PIPELINE_TOOL_MARKERS,
            "neutral_tools": NEUTRAL_TOOL_MARKERS,
            "annotation_identities": ANNOTATION_IDENTITIES,
            "dataflow_operations": DATAFLOW_OPERATIONS,
            "notebook_operations": NOTEBOOK_OPERATIONS,
            "pipeline_operations": PIPELINE_OPERATIONS,
            "neutral_operations": NEUTRAL_OPERATIONS,
        }.items()
    }
    return hashlib.sha256(json.dumps(payload, sort_keys=True).encode()).hexdigest()


SUPPORT_TABLE_FINGERPRINT = support_table_fingerprint()


def alteryx_support_for(plugin: str) -> str:
    """Classify an Alteryx plugin identity into a Fabric target category."""
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


def etl_support_for(operation: str) -> str:
    """Classify a normalized IR operation into a Fabric target category."""
    normalized = operation.casefold().replace(" ", "_")
    if normalized in NEUTRAL_OPERATIONS:
        return "neutral"
    if normalized in PIPELINE_OPERATIONS:
        return "pipeline"
    if normalized in NOTEBOOK_OPERATIONS:
        return "notebook"
    if normalized in DATAFLOW_OPERATIONS:
        return "dataflow"
    return "manual"


_SUPPORT_WEIGHTS: dict[str, int] = {
    "neutral": 0,
    "dataflow": 1,
    "pipeline": 2,
    "notebook": 3,
    "manual": 6,
}


def complexity_score(
    counts_by_support: list[tuple[str, int]],
    connection_count: int,
    *,
    dependency_count: int = 0,
) -> int:
    """Compute the deterministic Fabric complexity score from support-weighted counts."""
    weighted = sum(count * _SUPPORT_WEIGHTS[support] for support, count in counts_by_support)
    return weighted + connection_count + dependency_count * 2


def complexity_band(score: int) -> str:
    """Map a Fabric complexity score to Low, Medium, or High."""
    return "Low" if score < 20 else "Medium" if score < 40 else "High"


def recommend_target(
    support_types: set[str],
    unsupported_count: int,
    *,
    item_noun: str,
) -> tuple[str, tuple[str, ...], str]:
    """Select the static Fabric target, components, and explanation from support categories."""
    components = tuple(
        name
        for category, name in (
            ("dataflow", "Dataflow Gen2"),
            ("notebook", "Fabric Notebook"),
            ("pipeline", "Fabric Pipeline"),
        )
        if category in support_types
    )
    if not components:
        return (
            "Manual rework",
            (),
            f"{unsupported_count} {item_noun} type(s) have no deterministic mapping",
        )
    target = components[0] if len(components) == 1 else "Mixed Fabric solution"
    reason = (
        f"Deterministic mappings require {', '.join(components)}"
        if len(components) > 1
        else f"Detected {item_noun}s map to {components[0]}"
    )
    if unsupported_count:
        reason += (
            f"; {unsupported_count} unsupported {item_noun} type(s) require manual redesign"
        )
    return target, components, reason


def migration_wave(target: str, band: str) -> str:
    """Assign a static Fabric migration wave from target and complexity band."""
    if target == "Manual rework":
        return "Redesign"
    if target == "Mixed Fabric solution" or band == "High":
        return "Pilot"
    return "Wave 2" if band == "Medium" else "Wave 1"
