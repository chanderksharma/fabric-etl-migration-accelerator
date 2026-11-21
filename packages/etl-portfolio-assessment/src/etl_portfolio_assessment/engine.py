"""Target-neutral portfolio assessment over canonical ETL packages."""

from __future__ import annotations

from collections import Counter
from dataclasses import dataclass

from etl_migration_core.ir import AssetType, EtlAsset, EtlPackage, NodeKind, SourcePlatform
from etl_portfolio_assessment.effort import assessment_effort_days

NEUTRAL_ASSESSMENT_VERSION = "1.0.0"

NEUTRAL_OPERATIONS = frozenset({"annotation", "container", "end", "start"})
HEAVY_OPERATIONS = frozenset(
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
ORCHESTRATION_OPERATIONS = frozenset(
    {
        "assignment",
        "command",
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


@dataclass(frozen=True, slots=True)
class NeutralComponentItem:
    """Count and source-intrinsic classification for one normalized operation."""

    operation: str
    count: int
    classification: str


@dataclass(frozen=True, slots=True)
class NeutralAssetAssessment:
    """Target-agnostic portfolio assessment record for one canonical ETL asset."""

    native_id: str
    name: str
    folder: str | None
    source_platform: SourcePlatform
    source_product: str
    asset_type: AssetType
    component_count: int
    connection_count: int
    inventory: tuple[NeutralComponentItem, ...]
    complexity_score: int
    complexity_band: str
    intrinsic_effort_days: float
    wave_tier: str
    unknown_components: tuple[str, ...]
    dependencies: tuple[str, ...] = ()
    data_sources: tuple[str, ...] = ()
    rules_version: str = NEUTRAL_ASSESSMENT_VERSION


def classify_neutral_operation(operation: str, *, has_issues: bool = False) -> str:
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
    if normalized in {"unknown", "manual"}:
        return "manual"
    return "tabular"


def assess_package_neutral(package: EtlPackage) -> tuple[NeutralAssetAssessment, ...]:
    """Assess every asset in a canonical ETL package without target assumptions."""
    return tuple(_assess_asset_neutral(package, asset) for asset in package.assets)


def _assess_asset_neutral(
    package: EtlPackage,
    asset: EtlAsset,
) -> NeutralAssetAssessment:
    nodes = [
        node
        for graph in (*asset.mapping_graphs, asset.orchestration_graph)
        if graph is not None
        for node in graph.nodes
        if not node.disabled
    ]
    operations = [node.operation for node in nodes]
    if not operations:
        synthetic = {
            AssetType.MAPPING_TASK: "mapping_task",
            AssetType.TASKFLOW: "taskflow",
            AssetType.SESSION: "session",
            AssetType.WORKLET: "worklet",
        }.get(asset.asset_type)
        if synthetic:
            operations.append(synthetic)
    counts = Counter(operations)
    issue_ops = {node.operation for node in nodes if node.issues}
    inventory = tuple(
        NeutralComponentItem(
            operation=operation,
            count=count,
            classification=classify_neutral_operation(
                operation,
                has_issues=operation in issue_ops,
            ),
        )
        for operation, count in sorted(counts.items())
    )
    connection_count = sum(
        len({(edge.source, edge.target) for edge in graph.edges})
        for graph in (*asset.mapping_graphs, asset.orchestration_graph)
        if graph is not None
    )
    unknown = tuple(
        item.operation for item in inventory if item.classification == "manual"
    )
    score = sum(
        item.count
        * {
            "neutral": 0,
            "tabular": 1,
            "orchestration": 2,
            "script": 3,
            "manual": 6,
        }[item.classification]
        for item in inventory
    ) + connection_count + len(asset.dependencies) * 2
    band = "Low" if score < 20 else "Medium" if score < 40 else "High"
    wave_tier = (
        "Wave 4"
        if unknown
        else "Wave 2"
        if band == "High"
        else "Wave 3"
        if band == "Medium"
        else "Wave 1"
    )
    manual_count = sum(item.count for item in inventory if item.classification == "manual")
    dependencies = tuple(
        dict.fromkeys(
            dep.target_native_id
            for dep in asset.dependencies
            if dep.target_native_id
        )
    )
    data_sources = tuple(
        dict.fromkeys(
            [
                *(
                    conn.path or conn.name
                    for conn in asset.connections
                    if conn.path or conn.name
                ),
                *(
                    node.name
                    for graph in asset.mapping_graphs
                    for node in graph.nodes
                    if node.kind in {NodeKind.SOURCE, NodeKind.TARGET} and node.name
                ),
            ]
        )
    )
    return NeutralAssetAssessment(
        native_id=asset.native_id,
        name=asset.name,
        folder=asset.folder,
        source_platform=package.source_platform,
        source_product=package.source_product,
        asset_type=asset.asset_type,
        component_count=sum(counts.values()),
        connection_count=connection_count,
        inventory=inventory,
        complexity_score=score,
        complexity_band=band,
        intrinsic_effort_days=assessment_effort_days(
            unsupported_component_count=manual_count
        ),
        wave_tier=wave_tier,
        unknown_components=unknown,
        dependencies=dependencies,
        data_sources=data_sources,
    )
