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

ASSESSMENT_RULES_VERSION = "1.4.0"
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
