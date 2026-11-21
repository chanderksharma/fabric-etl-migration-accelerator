"""Fabric-classified evidence wrapper over etl_portfolio_assessment.evidence."""

from __future__ import annotations

from collections.abc import Callable
from pathlib import Path

from etl_migration_core.ir import EtlAsset, EtlPackage
from etl_portfolio_assessment.evidence import (
    MAX_NODES as MAX_NODES,
)
from etl_portfolio_assessment.evidence import (
    EvidenceEdge as EvidenceEdge,
)
from etl_portfolio_assessment.evidence import (
    EvidenceNode as EvidenceNode,
)
from etl_portfolio_assessment.evidence import (
    EvidenceResponse as EvidenceResponse,
)
from etl_portfolio_assessment.evidence import (
    WorkflowEvidence as WorkflowEvidence,
)
from etl_portfolio_assessment.evidence import (
    etl_asset_evidence as _base_etl_asset_evidence,
)
from etl_portfolio_assessment.evidence import (
    safe_expression as safe_expression,
)
from etl_portfolio_assessment.evidence import (
    safe_text as safe_text,
)
from etl_portfolio_assessment.evidence import (
    workflow_evidence as _base_workflow_evidence,
)
from etl_target_fabric.support_matrix import (
    alteryx_support_for,
    etl_support_for,
)


def workflow_evidence(
    path: Path,
    display_path: str,
    index: int,
    *,
    support_classifier: Callable[[str], str] | None = None,
) -> WorkflowEvidence:
    return _base_workflow_evidence(
        path,
        display_path,
        index,
        support_classifier=support_classifier or alteryx_support_for,
    )


def etl_asset_evidence(
    package: EtlPackage,
    asset: EtlAsset,
    display_path: str,
    index: int,
    *,
    support_classifier: Callable[[str], str] | None = None,
) -> WorkflowEvidence:
    return _base_etl_asset_evidence(
        package,
        asset,
        display_path,
        index,
        support_classifier=support_classifier or etl_support_for,
    )
