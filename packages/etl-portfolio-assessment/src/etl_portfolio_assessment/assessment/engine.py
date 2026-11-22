"""Target-neutral portfolio assessment over canonical ETL packages."""

from __future__ import annotations

import hashlib
import json
from collections import Counter
from dataclasses import dataclass

from etl_migration_core.contracts.ir import (
    AssetType,
    EtlAsset,
    EtlPackage,
    NodeKind,
    SourcePlatformId,
)
from etl_migration_core.contracts.operations import (
    HEAVY_OPERATIONS,
    NEUTRAL_OPERATIONS,
    ORCHESTRATION_OPERATIONS,
    TABULAR_OPERATIONS,
    classify_operation_category,
    operation_table_fingerprint,
)
from etl_portfolio_assessment.assessment.effort import (
    MAX_EFFORT_DAYS,
    MIN_EFFORT_DAYS,
    assessment_effort_days,
)

CLASSIFICATION_WEIGHTS: dict[str, int] = {
    "neutral": 0,
    "tabular": 1,
    "orchestration": 2,
    "script": 3,
    "manual": 6,
}
DEPENDENCY_WEIGHT = 2
MEDIUM_BAND_FLOOR = 20
HIGH_BAND_FLOOR = 40
WAVE_BY_BAND: dict[str, str] = {"Low": "Wave 1", "Medium": "Wave 3", "High": "Wave 2"}
MANUAL_REVIEW_WAVE = "Wave 4"

# Bump the semantic version for any rule or logic change. The fingerprint covers the data
# tables and constants above, so a forgotten bump still invalidates caches and fails the
# golden test instead of reusing stale results.
NEUTRAL_RULES_VERSION = "1.2.0"


def _rules_fingerprint() -> str:
    payload = {
        "operations": operation_table_fingerprint(),
        "weights": CLASSIFICATION_WEIGHTS,
        "dependency_weight": DEPENDENCY_WEIGHT,
        "band_floors": [MEDIUM_BAND_FLOOR, HIGH_BAND_FLOOR],
        "waves": WAVE_BY_BAND,
        "manual_review_wave": MANUAL_REVIEW_WAVE,
        "effort_days": [MIN_EFFORT_DAYS, MAX_EFFORT_DAYS],
    }
    digest = hashlib.sha256(json.dumps(payload, sort_keys=True).encode()).hexdigest()
    return digest[:12]


NEUTRAL_RULES_FINGERPRINT = _rules_fingerprint()
NEUTRAL_ASSESSMENT_VERSION = f"{NEUTRAL_RULES_VERSION}+{NEUTRAL_RULES_FINGERPRINT}"

__all__ = [
    "CLASSIFICATION_WEIGHTS",
    "HEAVY_OPERATIONS",
    "NEUTRAL_ASSESSMENT_VERSION",
    "NEUTRAL_OPERATIONS",
    "NEUTRAL_RULES_FINGERPRINT",
    "NEUTRAL_RULES_VERSION",
    "ORCHESTRATION_OPERATIONS",
    "TABULAR_OPERATIONS",
    "NeutralAssetAssessment",
    "NeutralComponentItem",
    "assess_package_neutral",
    "classify_neutral_operation",
]


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
    source_platform: SourcePlatformId
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
    return classify_operation_category(operation, has_issues=has_issues)


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
    counts = Counter(
        (node.operation, classify_neutral_operation(node.operation, has_issues=bool(node.issues)))
        for node in nodes
    )
    if not counts:
        synthetic = {
            AssetType.MAPPING_TASK: "mapping_task",
            AssetType.TASKFLOW: "taskflow",
            AssetType.SESSION: "session",
            AssetType.WORKLET: "worklet",
        }.get(asset.asset_type)
        if synthetic:
            counts[(synthetic, classify_neutral_operation(synthetic))] += 1
    inventory = tuple(
        NeutralComponentItem(
            operation=operation,
            count=count,
            classification=classification,
        )
        for (operation, classification), count in sorted(counts.items())
    )
    connection_count = sum(
        len({(edge.source, edge.target) for edge in graph.edges})
        for graph in (*asset.mapping_graphs, asset.orchestration_graph)
        if graph is not None
    )
    unknown = tuple(
        dict.fromkeys(item.operation for item in inventory if item.classification == "manual")
    )
    score = sum(
        item.count * CLASSIFICATION_WEIGHTS[item.classification] for item in inventory
    ) + connection_count + len(asset.dependencies) * DEPENDENCY_WEIGHT
    band = (
        "Low" if score < MEDIUM_BAND_FLOOR else "Medium" if score < HIGH_BAND_FLOOR else "High"
    )
    wave_tier = MANUAL_REVIEW_WAVE if unknown else WAVE_BY_BAND[band]
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
