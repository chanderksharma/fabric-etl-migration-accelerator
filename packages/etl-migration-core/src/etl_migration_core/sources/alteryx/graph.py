"""Versioned static workflow graph; no source or embedded code execution."""

import hashlib
import io
import math
import re
from collections import deque
from dataclasses import dataclass
from pathlib import Path
from xml.etree.ElementTree import Element, tostring

from defusedxml import ElementTree
from defusedxml.common import DefusedXmlException

from etl_migration_core.sources.base import SourceParseError
from etl_migration_core.sources.io import SourceChangedError, SourceTooLargeError, read_bounded

GRAPH_VERSION = "1.4.0"
MAX_WORKFLOW_BYTES = 100 * 1024 * 1024


class WorkflowParseError(SourceParseError):
    """A workflow does not meet the safe XML graph contract."""


@dataclass(frozen=True)
class GraphNode:
    id: str
    plugin: str
    name: str
    configuration: dict[str, str]
    disabled: bool
    engine_entry: str = ""
    macro: str = ""
    issues: tuple[str, ...] = ()
    label: str = ""
    x: float | None = None
    y: float | None = None
    width: float | None = None
    height: float | None = None


@dataclass(frozen=True)
class WorkflowGraph:
    nodes: tuple[GraphNode, ...]
    edges: tuple[tuple[str, str, str], ...]
    dependencies: tuple[str, ...]
    data_sources: tuple[str, ...]
    sha256: str
    execution_issues: tuple[str, ...] = ()
    schema_version: str = GRAPH_VERSION


def redact(value: str) -> str:
    """Remove credentials rather than persisting them in diagnostics or exports."""
    value = re.sub(r"(://)[^/\s]+@", r"\1[redacted]@", value)
    return re.sub(
        r"(?i)(password|pwd|token|secret|accountkey)\s*[=:]\s*[^;\s<]+",
        r"\1=[redacted]",
        value,
    )


@dataclass(frozen=True)
class ParsedWorkflow:
    """One parse result: the static graph plus root metadata from the same document."""

    graph: WorkflowGraph
    product_version: str | None


def parse_graph(path: Path) -> WorkflowGraph:
    return parse_workflow(path).graph


def parse_workflow(path: Path) -> ParsedWorkflow:
    try:
        content = read_bounded(path, MAX_WORKFLOW_BYTES)
        root: Element | None = None
        depth = -1
        elements = 0
        for event, element in ElementTree.iterparse(
            io.BytesIO(content),
            events=("start", "end"),
            forbid_dtd=True,
            forbid_entities=True,
            forbid_external=True,
        ):
            if event == "start":
                depth += 1
                elements += 1
                if root is None:
                    root = element
                if depth > 64 or elements > 100_000:
                    raise WorkflowParseError("XML nesting or element count exceeds parser limits")
            else:
                depth -= 1
    except SourceTooLargeError as error:
        raise WorkflowParseError("Workflow exceeds the parser size limit") from error
    except (
        ElementTree.ParseError,
        DefusedXmlException,
        OSError,
        SourceChangedError,
    ) as error:
        raise WorkflowParseError(f"Unable to parse {path.name}: {type(error).__name__}") from error
    if root is None:
        raise WorkflowParseError("Workflow has no XML root")
    for element in root.iter():
        element.tag = element.tag.rsplit("}", 1)[-1]
    if root.tag != "AlteryxDocument":
        raise WorkflowParseError(f"Unable to parse {path.name}: expected AlteryxDocument")
    product_version = root.get("yxmdVer")
    pending: list[tuple[Element, int]] = [(root, 0)]
    while pending:
        element, depth = pending.pop()
        if depth > 64:
            raise WorkflowParseError("XML nesting exceeds the parser depth limit")
        if any(marker in element.tag.casefold() for marker in ("password", "secret", "token")):
            element.text = "[redacted]"
            element.attrib.clear()
        elif element.text:
            element.text = redact(element.text)
        for key, value in element.attrib.items():
            element.set(
                key,
                "[redacted]"
                if any(marker in key.casefold() for marker in ("password", "secret", "token"))
                else redact(value),
            )
        pending.extend((child, depth + 1) for child in element)
    nodes: list[GraphNode] = []
    ids: set[str] = set()
    dependencies: set[str] = set()
    sources: set[str] = set()
    parents = {child: parent for parent in root.iter() for child in parent}
    for node in root.findall(".//Node"):
        if not _canvas_element(node, parents):
            continue
        identity = node.get("ToolID", "")
        if not identity or identity in ids:
            raise WorkflowParseError("Missing or duplicate ToolID")
        ids.add(identity)
        gui = node.find("GuiSettings")
        engine = node.find("EngineSettings")
        plugin = gui.get("Plugin", "") if gui is not None else ""
        if not plugin and engine is not None:
            plugin = engine.get("EngineDll", "")
        engine_entry = engine.get("EngineDllEntryPoint", "") if engine is not None else ""
        macro = engine.get("Macro", "") if engine is not None else ""
        config = node.find("Properties/Configuration")
        configuration: dict[str, str] = {}
        issues: list[str] = []
        if config is not None:
            for child in config:
                if child.tag in configuration:
                    issues.append(f"Repeated configuration element {child.tag}")
                    configuration[child.tag] = (
                        "<Repeated>"
                        + configuration[child.tag]
                        + tostring(child, encoding="unicode")
                        + "</Repeated>"
                    )
                else:
                    configuration[child.tag] = tostring(child, encoding="unicode")
            for file in config.findall(".//File"):
                if file.text:
                    sources.add(redact(file.text.strip()))
        if macro:
            dependencies.add(redact(macro))
        x, y, width, height = _node_position(node)
        disabled = False
        ancestor: Element | None = node
        while ancestor is not None:
            if ancestor.tag == "Node":
                for tag, off_value in (
                    ("Disabled", "true"),
                    ("Disable", "true"),
                    ("Enabled", "false"),
                ):
                    flag = ancestor.find(f"Properties/Configuration/{tag}")
                    if flag is not None:
                        value = flag.get("value", flag.text or "").strip().casefold()
                        disabled |= value == off_value
            ancestor = parents.get(ancestor)
        label = (
            (
                node.findtext("Properties/Configuration/Caption", default="")
                if width is not None and height is not None
                else ""
            )
            or (
                    node.findtext("Properties/Annotation/Name", default="")
                    or node.findtext(
                        "Properties/Annotation/DefaultAnnotationText", default=""
                    )
            )
        ).strip()
        nodes.append(
            GraphNode(
                id=identity,
                plugin=plugin,
                name=plugin.rsplit(".", 1)[-1].removesuffix("Tool"),
                configuration=configuration,
                disabled=disabled,
                engine_entry=engine_entry,
                macro=macro,
                issues=tuple(issues),
                label=label,
                x=x,
                y=y,
                width=width,
                height=height,
            )
        )
    edges: list[tuple[str, str, str]] = []
    for connection in root.findall(".//Connection"):
        if not _canvas_element(connection, parents):
            continue
        origin, destination = connection.find("Origin"), connection.find("Destination")
        if origin is None or destination is None:
            raise WorkflowParseError("Connection lacks an endpoint")
        source, target = origin.get("ToolID", ""), destination.get("ToolID", "")
        if source not in ids or target not in ids:
            raise WorkflowParseError("Connection references an unknown ToolID")
        edges.append((source, target, origin.get("Connection", "")))
    incoming = dict.fromkeys(ids, 0)
    following: dict[str, list[str]] = {identity: [] for identity in ids}
    for source, target, _ in edges:
        incoming[target] += 1
        following[source].append(target)
    ready = deque(identity for identity, count in incoming.items() if count == 0)
    visited = 0
    while ready:
        identity = ready.popleft()
        visited += 1
        for target in following[identity]:
            incoming[target] -= 1
            if incoming[target] == 0:
                ready.append(target)
    if visited != len(ids):
        raise WorkflowParseError("Workflow graph contains a cycle")
    return ParsedWorkflow(
        WorkflowGraph(
            tuple(nodes),
            tuple(edges),
            tuple(sorted(dependencies)),
            tuple(sorted(sources)),
            hashlib.sha256(content).hexdigest(),
            tuple(
                issue for event in root.iter("Events") if (issue := _event_issue(event)) is not None
            ),
        ),
        product_version,
    )


def _canvas_element(element: Element, parents: dict[Element, Element]) -> bool:
    ancestor = parents.get(element)
    while ancestor is not None:
        if ancestor.tag == "Configuration":
            return False
        ancestor = parents.get(ancestor)
    return True


def _node_position(
    node: Element,
) -> tuple[float | None, float | None, float | None, float | None]:
    position = node.find("GuiSettings/Position")
    if position is None:
        return None, None, None, None
    try:
        x = float(position.get("x", ""))
        y = float(position.get("y", ""))
        if not all(math.isfinite(value) and abs(value) < 1_000_000 for value in (x, y)):
            raise ValueError
        if not position.get("width") or not position.get("height"):
            return x, y, None, None
        width = float(position.get("width", ""))
        height = float(position.get("height", ""))
        if not all(
            math.isfinite(value) and 0 < value < 1_000_000
            for value in (width, height)
        ):
            raise ValueError
        return x, y, width, height
    except ValueError:
        return None, None, None, None


def _event_issue(events: Element) -> str | None:
    enabled = events.find("Enabled")
    if enabled is None:
        return "Workflow events have no explicit enabled state"
    value = enabled.get("value", enabled.text or "").strip().casefold()
    if value in {"false", "true"} and len(events) == 1:
        return None
    if value == "true":
        return "Executable workflow events require redesign"
    return "Workflow events use an ambiguous enabled state"
