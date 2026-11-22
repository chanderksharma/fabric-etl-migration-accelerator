"""Project a Fabric candidate into the target-neutral artifact contract.

The projection deliberately leaves ``files`` empty. ``write_candidates`` remains
the Fabric disk writer; this module must not create an artifact tree.
"""

from __future__ import annotations

from etl_migration_core.contracts.artifacts import ArtifactSet
from etl_target_fabric.compilers.alteryx import Candidate


def project_candidate(candidate: Candidate, *, platform_id: str = "fabric") -> ArtifactSet:
    """Return identity and diagnostics for one candidate, without file bytes."""
    return ArtifactSet(
        platform_id=platform_id,
        target_kind=candidate.target,
        workflow=candidate.workflow,
        validation_state=candidate.validation_state,
        translation_mode=candidate.translation_mode,
        deployable=candidate.deployable,
        files=(),
        diagnostics=tuple(candidate.diagnostics),
        required_bindings=tuple(candidate.required_bindings),
        metadata={
            "source_sha256": candidate.source_sha256,
            "code_sha256": candidate.code_sha256,
            "compiler_version": candidate.compiler_version,
            "source_platform": str(candidate.source_platform),
        },
    )
