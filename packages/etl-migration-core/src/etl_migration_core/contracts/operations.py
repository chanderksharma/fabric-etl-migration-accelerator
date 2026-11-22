"""Canonical target-neutral ETL operation categories."""

from __future__ import annotations

import hashlib
import json
from typing import Literal

OperationCategory = Literal["neutral", "tabular", "script", "orchestration", "manual"]

NEUTRAL_OPERATIONS: frozenset[str] = frozenset(
    {
        "annotation",
        "browse",
        "comment",
        "container",
        "end",
        "explorerbox",
        "start",
        "textbox",
        "toolcontainer",
    }
)

HEAVY_OPERATIONS: frozenset[str] = frozenset(
    {
        "advanced",
        "custom_transformation",
        "java",
        "python",
        "rtool",
        "script",
        "spatial",
        "predictive",
        "multirowformula",
    }
)

ORCHESTRATION_OPERATIONS: frozenset[str] = frozenset(
    {
        "assignment",
        "command",
        "controlcontainer",
        "decision",
        "detour",
        "download",
        "dynamicinput",
        "email",
        "mapping_task",
        "mappingtask",
        "runcommand",
        "session",
        "taskflow",
        "workflow",
        "worklet",
    }
)

TABULAR_OPERATIONS: frozenset[str] = frozenset(
    {
        "aggregator",
        "alteryxselect",
        "appendfields",
        "autofield",
        "crosstab",
        "datetime",
        "dbfileinput",
        "dbfileoutput",
        "expression",
        "filter",
        "formula",
        "inputdata",
        "join",
        "joiner",
        "lookup",
        "merge",
        "outputdata",
        "recordid",
        "regex",
        "router",
        "sample",
        "select",
        "sequence_generator",
        "sort",
        "sorter",
        "source",
        "source_qualifier",
        "summarize",
        "target",
        "textinput",
        "transpose",
        "union",
        "unique",
        "update_strategy",
        "xml_source_qualifier",
    }
)


def operation_table_fingerprint() -> str:
    """Hash every operation table so that any edit to them is a visible version change."""
    payload = {
        "neutral": sorted(NEUTRAL_OPERATIONS),
        "heavy": sorted(HEAVY_OPERATIONS),
        "orchestration": sorted(ORCHESTRATION_OPERATIONS),
        "tabular": sorted(TABULAR_OPERATIONS),
    }
    return hashlib.sha256(
        json.dumps(payload, sort_keys=True, separators=(",", ":")).encode()
    ).hexdigest()


def classify_operation_category(
    operation: str, *, has_issues: bool = False
) -> OperationCategory:
    """Classify a canonical operation purely by source semantics (target-free)."""
    if has_issues:
        return "manual"
    normalized = operation.casefold().replace(" ", "_")
    if normalized in NEUTRAL_OPERATIONS:
        return "neutral"
    if normalized in HEAVY_OPERATIONS:
        return "script"
    if normalized in ORCHESTRATION_OPERATIONS:
        return "orchestration"
    if normalized in TABULAR_OPERATIONS:
        return "tabular"
    return "manual"
