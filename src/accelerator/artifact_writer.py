"""Compatibility re-export of Fabric artifact writer from etl-target-fabric."""

from etl_target_fabric.artifact_writer import (
    ArtifactWriteResult as ArtifactWriteResult,
)
from etl_target_fabric.artifact_writer import (
    AssessmentTargetSummary as AssessmentTargetSummary,
)
from etl_target_fabric.artifact_writer import (
    _artifact_path as _artifact_path,
)
from etl_target_fabric.artifact_writer import (
    _candidate_artifact_path as _candidate_artifact_path,
)
from etl_target_fabric.artifact_writer import (
    build_candidate_package as build_candidate_package,
)
from etl_target_fabric.artifact_writer import (
    build_workflow_package as build_workflow_package,
)
from etl_target_fabric.artifact_writer import (
    write_candidates as write_candidates,
)
