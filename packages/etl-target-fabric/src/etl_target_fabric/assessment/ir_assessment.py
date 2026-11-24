"""Source-neutral assessment over canonical ETL packages."""

from __future__ import annotations

from collections import Counter
from dataclasses import dataclass

from etl_migration_core.contracts.ir import (
    AssetType,
    EtlAsset,
    EtlPackage,
    NodeKind,
    SourcePlatform,
)
from etl_migration_core.planning.effort import assessment_effort_days
from etl_target_fabric.assessment.support_matrix import (
    ASSESSMENT_RULES_VERSION as ASSESSMENT_RULES_VERSION,
)
from etl_target_fabric.assessment.support_matrix import (
    DATAFLOW_OPERATIONS as DATAFLOW_OPERATIONS,
)
from etl_target_fabric.assessment.support_matrix import (
    NEUTRAL_OPERATIONS as NEUTRAL_OPERATIONS,
)
from etl_target_fabric.assessment.support_matrix import (
    NOTEBOOK_OPERATIONS as NOTEBOOK_OPERATIONS,
)
from etl_target_fabric.assessment.support_matrix import (
    PIPELINE_OPERATIONS as PIPELINE_OPERATIONS,
)
from etl_target_fabric.assessment.support_matrix import (
    alteryx_support_for,
    complexity_band,
    complexity_score,
    migration_wave,
    recommend_target,
)
from etl_target_fabric.assessment.support_matrix import (
    etl_support_for as _support_for,
)

REGISTRY_VERSIONS = {
    SourcePlatform.ALTERYX: "2026.11.3",
    SourcePlatform.INFORMATICA_POWERCENTER: "2026.11.3",
    SourcePlatform.INFORMATICA_IDMC: "2026.11.1",
}


@dataclass(frozen=True, slots=True)
class ComponentInventoryItem:
    """Count and support status for one normalized operation."""

    operation: str
    count: int
    support: str


@dataclass(frozen=True, slots=True)
class EtlAssessment:
    """Deterministic assessment for one canonical ETL asset."""

    native_id: str
    name: str
    folder: str | None
    source_platform: SourcePlatform
    source_product: str
    asset_type: AssetType
    component_count: int
    connection_count: int
    inventory: tuple[ComponentInventoryItem, ...]
    complexity_score: int
    complexity_band: str
    recommended_target: str
    target_components: tuple[str, ...]
    recommendation_reason: str
    unsupported_components: tuple[str, ...]
    migration_wave: str
    estimated_effort_days: float
    registry_version: str
    dependencies: tuple[str, ...] = ()
    data_sources: tuple[str, ...] = ()
    rules_version: str = ASSESSMENT_RULES_VERSION


def assess_package(package: EtlPackage) -> tuple[EtlAssessment, ...]:
    """Assess every asset in a canonical ETL package."""
    return tuple(_assess_asset(package, asset) for asset in package.assets)


def _assess_asset(package: EtlPackage, asset: EtlAsset) -> EtlAssessment:
    if not isinstance(package.source_platform, SourcePlatform):
        raise ValueError(f"Fabric assessment does not support source {package.source_platform!r}")
    active_nodes = [
        node
        for graph in (*asset.mapping_graphs, asset.orchestration_graph)
        if graph is not None
        for node in graph.nodes
        if not node.disabled
    ]
    def _node_support(node_op: str, native_type: str | None, issues: tuple[str, ...]) -> str:
        if issues:
            return "manual"
        if package.source_platform is SourcePlatform.ALTERYX and native_type:
            return alteryx_support_for(native_type)
        return _support_for(node_op)

    counts: Counter[tuple[str, str]] = Counter(
        (
            node.operation,
            _node_support(node.operation, node.native_type, node.issues),
        )
        for node in active_nodes
    )
    if not counts:
        synthetic = {
            AssetType.MAPPING_TASK: "mapping_task",
            AssetType.TASKFLOW: "taskflow",
            AssetType.SESSION: "session",
            AssetType.WORKLET: "worklet",
        }.get(asset.asset_type)
        if synthetic:
            counts[(synthetic, _support_for(synthetic))] += 1
    inventory = tuple(
        ComponentInventoryItem(
            operation=operation,
            count=count,
            support=support,
        )
        for (operation, support), count in sorted(counts.items())
    )
    connection_count = sum(
        len(
            {
                (edge.source, edge.target)
                for edge in graph.edges
                if edge.source in active_ids and edge.target in active_ids
            }
        )
        for graph in (*asset.mapping_graphs, asset.orchestration_graph)
        if graph is not None
        for active_ids in ({node.native_id for node in graph.nodes if not node.disabled},)
    )
    unsupported = tuple(
        dict.fromkeys(item.operation for item in inventory if item.support == "manual")
    )
    score = complexity_score(
        [(item.support, item.count) for item in inventory],
        connection_count,
        dependency_count=len(asset.dependencies),
    )
    band = complexity_band(score)
    target, components, reason = recommend_target(
        {item.support for item in inventory},
        len(unsupported),
        item_noun="component",
    )
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
    return EtlAssessment(
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
        recommended_target=target,
        target_components=components,
        recommendation_reason=reason,
        unsupported_components=unsupported,
        migration_wave=migration_wave(target, band),
        estimated_effort_days=_estimated_effort(inventory),
        registry_version=REGISTRY_VERSIONS[package.source_platform],
        dependencies=dependencies,
        data_sources=data_sources,
    )


def _estimated_effort(
    inventory: tuple[ComponentInventoryItem, ...],
) -> float:
    unsupported_count = sum(
        item.count for item in inventory if item.support == "manual"
    )
    return assessment_effort_days(
        unsupported_component_count=unsupported_count,
    )

