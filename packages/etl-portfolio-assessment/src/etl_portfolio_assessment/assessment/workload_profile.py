"""Target-neutral static workload profiling over canonical ETL packages."""

from __future__ import annotations

from collections import Counter
from typing import Literal

from etl_migration_core.contracts.ir import EtlAsset, EtlPackage, NodeKind
from etl_migration_core.contracts.spi import NeutralWorkloadProfile
from etl_portfolio_assessment.assessment.engine import classify_neutral_operation


def extract_workload_profile(
    package: EtlPackage,
    asset: EtlAsset,
) -> NeutralWorkloadProfile:
    """Extract target-agnostic static workload counts from one canonical ETL asset."""
    counts: Counter[str] = Counter()
    total_steps = 0
    heavy_steps = 0
    script_steps = 0
    orchestration_steps = 0

    for graph in (*asset.mapping_graphs, asset.orchestration_graph):
        if graph is None:
            continue
        for node in graph.nodes:
            if node.disabled:
                continue
            classification = classify_neutral_operation(
                node.operation,
                has_issues=bool(node.issues),
            )
            if classification == "neutral":
                continue
            total_steps += 1
            if node.kind is NodeKind.SOURCE:
                counts["sources"] += 1
            elif node.kind is NodeKind.TARGET:
                counts["targets"] += 1
            elif classification == "script":
                counts["scripts"] += 1
                script_steps += 1
                heavy_steps += 1
            elif classification == "orchestration":
                counts["orchestration"] += 1
                orchestration_steps += 1
            elif classification == "manual":
                counts["manual"] += 1
                heavy_steps += 1
            else:
                counts["transforms"] += 1
                if node.operation in {"join", "joiner", "merge", "union", "lookup"}:
                    heavy_steps += 1

    counts["connections"] = len(asset.connections)
    counts["dependencies"] = len(asset.dependencies)

    profile_kind: Literal["alteryx", "informatica"] = (
        "alteryx"
        if package.source_platform.value == "alteryx"
        else "informatica"
    )
    cap_meta = asset.metadata.get("capacity")
    covered = (
        bool(cap_meta.get("covered_by_linked_mapping", False))
        if isinstance(cap_meta, dict)
        else False
    )
    return NeutralWorkloadProfile(
        source_platform=package.source_platform,
        profile_kind=profile_kind,
        counts=dict(sorted(counts.items())),
        total_steps=total_steps,
        heavy_steps=heavy_steps,
        script_steps=script_steps,
        orchestration_steps=orchestration_steps,
        covered_by_linked_mapping=covered,
    )
