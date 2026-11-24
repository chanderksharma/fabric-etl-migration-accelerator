"""Pure dev deployment planning; no cloud client or network imports."""

from __future__ import annotations

from collections.abc import Sequence

from pydantic import BaseModel

from etl_migration_core.contracts.spi import TargetArtifact, TargetDryRunResult
from etl_target_fabric.compilers.alteryx import Candidate


class DryRunResult(BaseModel):
    allowed: bool = False
    workspace: str
    blockers: list[str]
    warnings: list[str] = []
    planned_mutations: list[str] = []


def _plan_items(
    items: Sequence[tuple[str, str, bool, bool]],
    *,
    approved_workspace: str | None,
    requested_workspace: str,
    item_noun: str,
) -> tuple[list[str], list[str], list[str]]:
    blockers: list[str] = []
    if not approved_workspace:
        blockers.append("An approved dev workspace identity has not been configured")
    elif requested_workspace != approved_workspace:
        blockers.append("Requested workspace is not the approved dev workspace")
    if not items:
        blockers.append(f"No generated {item_noun}s were supplied")
    if any(not deployable for _, _, deployable, _ in items):
        blockers.append(f"One or more {item_noun}s have no deployable Fabric definition")
    warnings = [
        "Generated definitions are unvalidated and require independent semantic parity",
        *(
            ["One or more items require runtime source bindings after deployment"]
            if any(not runtime_ready for _, _, _, runtime_ready in items)
            else []
        ),
    ]
    mutations = [
        f"Create {target_kind} item for {workflow}"
        for workflow, target_kind, deployable, _ in items
        if deployable
    ]
    return blockers, warnings, mutations


def dry_run(
    candidates: list[Candidate], *, approved_workspace: str | None, requested_workspace: str
) -> DryRunResult:
    blockers, warnings, mutations = _plan_items(
        [
            (c.workflow, c.target, c.deployable, c.runtime_ready)
            for c in candidates
        ],
        approved_workspace=approved_workspace,
        requested_workspace=requested_workspace,
        item_noun="candidate",
    )
    return DryRunResult(
        allowed=not blockers,
        workspace=requested_workspace,
        blockers=blockers,
        warnings=warnings,
        planned_mutations=mutations,
    )


def plan_target_dry_run(
    artifacts: Sequence[TargetArtifact],
    *,
    approved_destination: str | None,
    requested_destination: str,
    provider_version: str = "1.0.0",
) -> TargetDryRunResult:
    """Build a Target SPI ``TargetDryRunResult`` using the shared Fabric planning rules."""
    blockers, warnings, mutations = _plan_items(
        [
            (
                a.workflow,
                a.target_kind,
                a.deployable,
                bool(a.metadata.get("runtime_ready")),
            )
            for a in artifacts
        ],
        approved_workspace=approved_destination,
        requested_workspace=requested_destination,
        item_noun="artifact",
    )
    return TargetDryRunResult(
        platform_id="fabric",
        provider_version=provider_version,
        allowed=not blockers,
        destination=requested_destination,
        blockers=tuple(blockers),
        warnings=tuple(warnings),
        planned_mutations=tuple(mutations),
    )
