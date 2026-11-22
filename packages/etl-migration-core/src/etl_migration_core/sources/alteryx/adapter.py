"""Compatibility adapter from Alteryx workflows to the canonical ETL IR."""

from __future__ import annotations

from pathlib import Path

from etl_migration_core.contracts.ir import (
    AssetType,
    EtlAsset,
    EtlConnectionRef,
    EtlContainer,
    EtlDependency,
    EtlEdge,
    EtlGraph,
    EtlNode,
    EtlPackage,
    GraphKind,
    NodeKind,
    SourceLocation,
    SourcePlatform,
)
from etl_migration_core.sources.alteryx.graph import (
    GraphNode,
    WorkflowGraph,
    parse_workflow,
)
from etl_migration_core.sources.base import SourceMatch

ALTERYX_EXTENSIONS = frozenset({".yxmd", ".yxmc", ".yxwz"})


class AlteryxSourceAdapter:
    """Parse existing Alteryx formats without changing legacy behavior."""

    adapter_id = "alteryx"
    platform = SourcePlatform.ALTERYX
    product = "Alteryx Designer"
    adapter_version = "1.0.0"
    parser_version = "1.3.0"
    registry_version = "2026.11.3"
    rules_version = "1.3.0"

    def probe(self, path: Path, display_path: str) -> SourceMatch | None:
        """Recognize staged Alteryx XML workflow files."""
        if path.suffix.casefold() not in ALTERYX_EXTENSIONS or not path.is_file():
            return None
        with path.open("rb") as stream:
            head = stream.read(64_000)
        return self._match_head(head, path.suffix.casefold(), display_path)

    def probe_bytes(self, content: bytes, display_path: str) -> SourceMatch | None:
        """Recognize Alteryx XML bytes without touching disk."""
        suffix = Path(display_path.split("!")[-1]).suffix.casefold()
        if suffix not in ALTERYX_EXTENSIONS:
            return None
        return self._match_head(content[:64_000], suffix, display_path)

    def _match_head(
        self, head: bytes, suffix: str, display_path: str
    ) -> SourceMatch | None:
        if b"<AlteryxDocument" not in head:
            return None
        asset_type = {
            ".yxmc": "macro",
            ".yxwz": "analytic_app",
        }.get(suffix, "workflow")
        return SourceMatch(
            adapter_id=self.adapter_id,
            platform=self.platform,
            product=self.product,
            asset_type=asset_type,
            confidence=100,
            display_path=display_path,
        )

    def parse(self, path: Path, match: SourceMatch) -> EtlPackage:
        """Convert an Alteryx workflow graph to canonical ETL IR."""
        return self.parse_with_graph(path, match)[0]

    def parse_with_graph(self, path: Path, match: SourceMatch) -> tuple[EtlPackage, WorkflowGraph]:
        """Parse once and return both the canonical IR and the legacy graph for Fabric engines."""
        parsed = parse_workflow(path)
        graph = parsed.graph
        asset_type = {
            ".yxmc": AssetType.MAPPLET,
            ".yxwz": AssetType.WORKFLOW,
        }.get(path.suffix.casefold(), AssetType.WORKFLOW)
        nodes = tuple(_node_to_ir(node, match.display_path) for node in graph.nodes)
        containers = _containers(graph.nodes)
        mapping = EtlGraph(
            kind=GraphKind.MAPPING,
            nodes=nodes,
            edges=tuple(
                EtlEdge(source=source, target=target, source_port=anchor or None)
                for source, target, anchor in graph.edges
            ),
            containers=containers,
        )
        dependencies = tuple(
            EtlDependency(
                source_native_id=path.stem,
                target_native_id=dependency,
                kind="macro",
            )
            for dependency in graph.dependencies
        )
        connections = tuple(
            EtlConnectionRef(
                native_id=f"source-{index}",
                name=Path(source).name or source,
                kind="source_path",
                path=source,
            )
            for index, source in enumerate(graph.data_sources, start=1)
        )
        asset = EtlAsset(
            native_id=path.stem,
            name=path.stem,
            asset_type=asset_type,
            mapping_graphs=(mapping,),
            dependencies=dependencies,
            connections=connections,
            source_location=SourceLocation(path=match.display_path),
        )
        return (
            EtlPackage(
                source_platform=self.platform,
                source_product=self.product,
                product_version=parsed.product_version,
                export_id=match.display_path,
                source_sha256=graph.sha256,
                assets=(asset,),
                connections=connections,
            ),
            graph,
        )

    def legacy_graph(self, path: Path) -> WorkflowGraph:
        """Return the versioned Alteryx graph for compatibility callers."""
        return parse_workflow(path).graph


def _node_to_ir(node: GraphNode, display_path: str) -> EtlNode:
    raw_op = node.name or node.plugin.rsplit(".", 1)[-1] or "unknown"
    operation = raw_op.strip().casefold() or "unknown"
    display_name = (node.label or node.name or operation).strip() or f"Node {node.id}"
    if operation in {"inputdata", "dbfileinput", "textinput"}:
        kind = NodeKind.SOURCE
    elif operation in {"outputdata", "dbfileoutput", "browse"}:
        kind = NodeKind.TARGET
    elif operation == "toolcontainer":
        kind = NodeKind.CONTAINER
    elif operation in {"comment", "explorerbox", "textbox"}:
        kind = NodeKind.ANNOTATION
    else:
        kind = NodeKind.TRANSFORMATION
    return EtlNode(
        native_id=node.id,
        name=display_name,
        operation=operation,
        kind=kind,
        native_type=node.plugin,
        label=node.label,
        disabled=node.disabled,
        properties=dict(node.configuration),
        issues=node.issues,
        source_location=SourceLocation(path=display_path, object_path=f"Node[{node.id}]"),
        x=node.x,
        y=node.y,
        width=node.width,
        height=node.height,
    )


def _containers(nodes: tuple[GraphNode, ...]) -> tuple[EtlContainer, ...]:
    container_nodes = [
        node
        for node in nodes
        if node.name.casefold() == "toolcontainer"
        and node.x is not None
        and node.y is not None
        and node.width is not None
        and node.height is not None
    ]
    results: list[EtlContainer] = []
    for container in container_nodes:
        parents = [
            candidate
            for candidate in container_nodes
            if candidate.id != container.id
            and _area(candidate) > _area(container)
            and _contains_box(candidate, container)
        ]
        parent = min(parents, key=_area, default=None)
        members = tuple(
            node.id
            for node in nodes
            if node.id != container.id
            and node.x is not None
            and node.y is not None
            and _contains_point(container, node.x, node.y)
        )
        results.append(
            EtlContainer(
                native_id=container.id,
                name=container.label or f"Container {container.id}",
                parent_id=parent.id if parent else None,
                member_ids=members,
            )
        )
    return tuple(results)


def _area(node: GraphNode) -> float:
    return (node.width or 0) * (node.height or 0)


def _contains_point(container: GraphNode, x: float, y: float) -> bool:
    assert container.x is not None
    assert container.y is not None
    assert container.width is not None
    assert container.height is not None
    return (
        container.x <= x <= container.x + container.width
        and container.y <= y <= container.y + container.height
    )


def _contains_box(parent: GraphNode, child: GraphNode) -> bool:
    assert child.x is not None
    assert child.y is not None
    assert child.width is not None
    assert child.height is not None
    return _contains_point(parent, child.x, child.y) and _contains_point(
        parent,
        child.x + child.width,
        child.y + child.height,
    )
