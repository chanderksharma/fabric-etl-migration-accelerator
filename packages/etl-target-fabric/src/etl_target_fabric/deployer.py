"""Pure dev deployment planning; no cloud client or network imports."""

from pydantic import BaseModel

from etl_target_fabric.generation import Candidate


class DryRunResult(BaseModel):
    allowed: bool = False
    workspace: str
    blockers: list[str]
    warnings: list[str] = []
    planned_mutations: list[str] = []


def dry_run(
    candidates: list[Candidate], *, approved_workspace: str | None, requested_workspace: str
) -> DryRunResult:
    blockers: list[str] = []
    if not approved_workspace:
        blockers.append("An approved dev workspace identity has not been configured")
    elif requested_workspace != approved_workspace:
        blockers.append("Requested workspace is not the approved dev workspace")
    if not candidates:
        blockers.append("No generated candidates were supplied")
    if any(not candidate.deployable for candidate in candidates):
        blockers.append("One or more candidates have no deployable Fabric definition")
    warnings = [
        "Generated definitions are unvalidated and require independent semantic parity",
        *(
            ["One or more items require runtime source bindings after deployment"]
            if any(not candidate.runtime_ready for candidate in candidates)
            else []
        ),
    ]
    mutations = [
        f"Create {candidate.target} item for {candidate.workflow}"
        for candidate in candidates
        if candidate.deployable
    ]
    return DryRunResult(
        allowed=not blockers,
        workspace=requested_workspace,
        blockers=blockers,
        warnings=warnings,
        planned_mutations=mutations,
    )
