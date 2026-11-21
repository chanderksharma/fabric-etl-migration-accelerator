"""Read-only, bounded presentation evidence for confirmed workflow snapshots."""

import hashlib
import re
from collections.abc import Callable
from pathlib import Path
from typing import Literal

from defusedxml import ElementTree
from pydantic import BaseModel, Field

from etl_migration_core.contracts.ir import EtlAsset, EtlPackage
from etl_migration_core.sources.alteryx import AlteryxSourceAdapter
from etl_migration_core.sources.alteryx.graph import (
    GRAPH_VERSION,
    WorkflowParseError,
    _canvas_element,
    redact,
)
from etl_portfolio_assessment.assessment.engine import classify_neutral_operation

MAX_NODES = 500


class EvidenceNode(BaseModel):
    id: str = Field(max_length=128)
    name: str = Field(max_length=256)
    label: str = Field(default="", max_length=256)
    plugin: str = Field(max_length=512)
    support: str
    disabled: bool
    x: float | None = None
    y: float | None = None
    width: float | None = None
    height: float | None = None
    expressions: list[str] = Field(default_factory=list)
    issues: list[str] = Field(default_factory=list)


class EvidenceEdge(BaseModel):
    source: str
    target: str
    source_anchor: str
    target_anchor: str


class WorkflowEvidence(BaseModel):
    workflow_index: int
    workflow_path: str = Field(max_length=4096)
    source_sha256: str
    source_version: str | None = None
    purpose: str | None = None
    parse_status: Literal["parsed", "failed"] = "parsed"
    layout_source: Literal["source", "derived"] = "derived"
    nodes: list[EvidenceNode] = Field(default_factory=list)
    edges: list[EvidenceEdge] = Field(default_factory=list)
    findings: list[str] = Field(default_factory=list)
    node_count: int = 0
    edge_count: int = 0
    truncated: bool = False


class EvidenceResponse(BaseModel):
    schema_version: str = "1.1.0"
    graph_version: str = GRAPH_VERSION
    run_id: str
    snapshot_id: str
    total_workflows: int
    workflows: list[WorkflowEvidence]
    truncated: bool = False


def safe_text(value: str, limit: int = 2000) -> str:
    value = redact(value)
    value = re.sub(r"(?i)\bbearer\s+[A-Za-z0-9._~-]+", "Bearer [redacted]", value)
    value = re.sub(r"\beyJ[A-Za-z0-9_-]+\.[A-Za-z0-9_-]+\.[A-Za-z0-9_-]+\b", "[redacted]", value)
    value = re.sub(
        r"""(?i)(\[(?:password|pwd|token|secret|accountkey)\]\s*=\s*)(["']).*?\2""",
        r"\1'[redacted]'",
        value,
    )
    return value[:limit]


def safe_expression(value: str) -> str:
    if re.search(r"(?i)\b(password|pwd|token|secret|key|accountkey|bearer)\b", value):
        return "[Credential-bearing expression withheld]"
    return safe_text(value, 256)


def workflow_evidence(
    path: Path,
    display_path: str,
    index: int,
    *,
    support_classifier: Callable[[str], str] | None = None,
) -> WorkflowEvidence:
    classifier = support_classifier or (
        lambda plugin: classify_neutral_operation(plugin.rsplit(".", 1)[-1])
    )
    result = WorkflowEvidence(workflow_index=index, workflow_path=display_path, source_sha256="")
    try:
        graph = AlteryxSourceAdapter().legacy_graph(path)
    except WorkflowParseError as error:
        result.parse_status = "failed"
        result.findings = [safe_text(str(error))]
        return result
    content = path.read_bytes()
    if hashlib.sha256(content).hexdigest() != graph.sha256:
        raise ValueError("Workflow changed during evidence extraction")
    root = ElementTree.fromstring(
        content, forbid_dtd=True, forbid_entities=True, forbid_external=True
    )
    for element in root.iter():
        element.tag = element.tag.rsplit("}", 1)[-1]
    parents = {child: parent for parent in root.iter() for child in parent}
    description = root.find("MetaInfo/Description")
    result.purpose = (
        safe_text(description.text) if description is not None and description.text else None
    )
    result.source_version = safe_text(root.get("yxmdVer", ""), 100) or None
    result.source_sha256 = graph.sha256
    result.node_count = len(graph.nodes)
    result.edge_count = len(graph.edges)
    result.truncated = len(graph.nodes) > MAX_NODES
    result.findings = [safe_text(value, 500) for value in graph.execution_issues[:200]]
    for node in graph.nodes[:MAX_NODES]:
        expressions: list[str] = []
        for key, xml in node.configuration.items():
            if key not in {"Expression", "FormulaFields", "FilterExpression"}:
                continue
            configuration = ElementTree.fromstring(
                xml, forbid_dtd=True, forbid_entities=True, forbid_external=True
            )
            for element in configuration.iter():
                expression = element.get("expression") or (
                    element.text if element.tag in {"Expression", "FilterExpression"} else None
                )
                if expression:
                    expressions.append(safe_expression(expression))
        item = EvidenceNode(
            id=node.id,
            name=safe_text(node.name, 256),
            label=safe_text(node.label, 256),
            plugin=safe_text(node.plugin, 512),
            support=classifier(node.plugin),
            disabled=node.disabled,
            x=node.x,
            y=node.y,
            width=node.width,
            height=node.height,
            expressions=expressions[:10],
            issues=[safe_text(issue, 256) for issue in node.issues[:5]],
        )
        result.nodes.append(item)
        result.findings.extend(
            f"Tool {node.id}: {safe_text(issue, 500)}" for issue in node.issues[:5]
        )
    included = {node.id for node in result.nodes}
    for connection in root.findall(".//Connection"):
        if not _canvas_element(connection, parents):
            continue
        origin, destination = connection.find("Origin"), connection.find("Destination")
        if origin is None or destination is None:
            continue
        source, target = origin.get("ToolID", ""), destination.get("ToolID", "")
        if source in included and target in included:
            result.edges.append(
                EvidenceEdge(
                    source=source,
                    target=target,
                    source_anchor=safe_text(origin.get("Connection", ""), 100),
                    target_anchor=safe_text(destination.get("Connection", ""), 100),
                )
            )
            if len(result.edges) >= 1000:
                break
    result.layout_source = (
        "source"
        if result.nodes and all(node.x is not None and node.y is not None for node in result.nodes)
        else "derived"
    )
    result.findings = result.findings[:200]
    result.truncated |= len(result.edges) < result.edge_count
    return result


def etl_asset_evidence(
    package: EtlPackage,
    asset: EtlAsset,
    display_path: str,
    index: int,
    *,
    support_classifier: Callable[[str], str] | None = None,
) -> WorkflowEvidence:
    """Project canonical ETL graphs into the bounded presentation evidence schema."""
    classifier = support_classifier or classify_neutral_operation
    asset_path = "/".join(part for part in (asset.folder, asset.name) if part)
    workflow_path = f"{display_path}!{asset_path}" if asset_path else display_path
    graphs = (
        *asset.mapping_graphs,
        *((asset.orchestration_graph,) if asset.orchestration_graph is not None else ()),
    )
    result = WorkflowEvidence(
        workflow_index=index,
        workflow_path=workflow_path,
        source_sha256=package.source_sha256 or "",
        source_version=package.product_version or package.export_version,
        purpose=safe_text(asset.description) if asset.description else None,
    )
    if not graphs:
        result.findings = ["No normalized graph is available for this source asset"]
        return result
    result.node_count = sum(len(graph.nodes) for graph in graphs)
    result.edge_count = sum(
        len({(edge.source, edge.target) for edge in graph.edges})
        for graph in graphs
    )
    result.truncated = result.node_count > MAX_NODES or result.edge_count > 1000
    used_ids: set[str] = set()
    id_maps: list[dict[str, str]] = []
    for graph_index, graph in enumerate(graphs):
        id_map: dict[str, str] = {}
        for node in graph.nodes:
            identity = safe_text(node.native_id, 128)
            if identity in used_ids:
                identity = safe_text(
                    f"{graph.kind.value}-{graph_index + 1}:{node.native_id}",
                    128,
                )
            used_ids.add(identity)
            id_map[node.native_id] = identity
            if len(result.nodes) >= MAX_NODES:
                continue
            result.nodes.append(
                EvidenceNode(
                    id=identity,
                    name=safe_text(node.name, 256),
                    label=safe_text(node.label, 256),
                    plugin=safe_text(node.native_type or node.operation, 512),
                    support=(
                        "manual"
                        if node.issues
                        else classifier(node.operation)
                    ),
                    disabled=node.disabled,
                    x=node.x,
                    y=node.y,
                    width=node.width,
                    height=node.height,
                    expressions=[
                        safe_expression(port.expression)
                        for port in node.ports
                        if port.expression
                    ][:10],
                    issues=[safe_text(issue, 256) for issue in node.issues[:5]],
                )
            )
        id_maps.append(id_map)
    included = {node.id for node in result.nodes}
    for graph, id_map in zip(graphs, id_maps, strict=True):
        seen_edges: set[tuple[str, str]] = set()
        for edge in graph.edges:
            key = (edge.source, edge.target)
            if key in seen_edges:
                continue
            seen_edges.add(key)
            source = id_map[edge.source]
            target = id_map[edge.target]
            if (
                source not in included
                or target not in included
                or len(result.edges) >= 1000
            ):
                continue
            result.edges.append(
                EvidenceEdge(
                    source=source,
                    target=target,
                    source_anchor=edge.source_port or "Output",
                    target_anchor=edge.target_port or "Input",
                )
            )
    result.findings = [
        f"Node {node.native_id}: {safe_text(issue, 500)}"
        for graph in graphs
        for node in graph.nodes
        for issue in node.issues[:5]
    ][:200]
    result.layout_source = (
        "source"
        if result.nodes and all(node.x is not None and node.y is not None for node in result.nodes)
        else "derived"
    )
    return result
