"""Content-addressed identities: snapshot IDs, file digests, and incremental-cache keys.

Every version that can change a stored result is folded into its key, so a stale cache
entry can never be returned after an engine, adapter, or rule change.
"""

from __future__ import annotations

import hashlib
import json
from collections.abc import Iterable
from pathlib import Path

from etl_migration_core.contracts.ir import (
    EXTENSIBLE_SOURCE_IR_VERSION,
    IR_VERSION,
    SourcePlatform,
)
from etl_migration_core.intake.discovery import hash_idmc_directory
from etl_migration_core.intake.domain import WorkflowCandidate
from etl_migration_core.sources.alteryx.graph import GRAPH_VERSION
from etl_migration_core.sources.registry import SourceAdapterRegistry
from etl_portfolio_assessment.assessment.engine import NEUTRAL_ASSESSMENT_VERSION
from etl_target_fabric.assessment.ir_assessment import ASSESSMENT_RULES_VERSION
from etl_target_fabric.assessment.schemas import WorkflowCandidateResponse
from etl_target_fabric.assessment.support_matrix import SUPPORT_TABLE_FINGERPRINT
from etl_target_fabric.assessment.workflow import REGISTRY_VERSION, RULES_VERSION
from etl_target_fabric.capacity.model import CAPACITY_MODEL_VERSION
from etl_target_fabric.compilers.alteryx import COMPILER_VERSION
from etl_target_fabric.compilers.ir import ETL_COMPILER_VERSION

COPY_BUFFER_BYTES = 1024 * 1024


def _digest(parts: list[object]) -> str:
    return hashlib.sha256(json.dumps(parts).encode()).hexdigest()


def snapshot_id(workflows: Iterable[WorkflowCandidate | WorkflowCandidateResponse]) -> str:
    """Identify a confirmed set of files together with the engine versions that read them."""
    identity = json.dumps(
        {
            "files": [
                (
                    item.display_path,
                    item.sha256,
                    item.source_platform,
                    item.adapter_version,
                    *(
                        (item.adapter_id,)
                        if not isinstance(item.source_platform, SourcePlatform)
                        else ()
                    ),
                    *(
                        (item.parser_version, item.registry_version, item.rules_version)
                        if not isinstance(item.source_platform, SourcePlatform)
                        and any((item.parser_version, item.registry_version, item.rules_version))
                        else ()
                    ),
                )
                for item in workflows
            ],
            "versions": [GRAPH_VERSION, REGISTRY_VERSION, RULES_VERSION, IR_VERSION],
        },
        sort_keys=True,
    )
    return hashlib.sha256(identity.encode()).hexdigest()


def sha256_file(path: Path) -> str:
    """Hash a file, or an extracted IDMC directory, without loading it into memory."""
    if path.is_dir():
        return hash_idmc_directory(path)[0]
    with path.open("rb") as stream:
        return hashlib.file_digest(stream, "sha256").hexdigest()


def copy_with_sha256(source: Path, destination: Path) -> str:
    """Copy a file while hashing it, so the stored copy is verified against its source."""
    digest = hashlib.sha256()
    with source.open("rb") as input_stream, destination.open("wb") as output_stream:
        while chunk := input_stream.read(COPY_BUFFER_BYTES):
            output_stream.write(chunk)
            digest.update(chunk)
    return digest.hexdigest()


def ir_cache_key(registry: SourceAdapterRegistry, item: WorkflowCandidateResponse) -> str:
    """Key for the parsed canonical IR of one confirmed file."""
    adapter_versions = tuple(
        (adapter.adapter_id, adapter.adapter_version, adapter.parser_version)
        for adapter in registry.adapters
        if adapter.adapter_id == item.adapter_id or adapter.platform == item.source_platform
    )
    return _digest(
        [
            item.sha256,
            item.display_path,
            item.source_platform,
            item.adapter_id,
            item.adapter_version,
            item.parser_version,
            adapter_versions,
            GRAPH_VERSION,
            IR_VERSION,
            EXTENSIBLE_SOURCE_IR_VERSION,
        ]
    )


def assessment_cache_key(registry: SourceAdapterRegistry, item: WorkflowCandidateResponse) -> str:
    """Key for the target-aware (Fabric) assessment of one confirmed file."""
    source_versions: tuple[object, ...] = (
        (
            tuple(
                (
                    adapter.adapter_id,
                    adapter.adapter_version,
                    adapter.parser_version,
                    adapter.registry_version,
                    adapter.rules_version,
                )
                for adapter in registry.adapters
                if adapter.platform == item.source_platform
            ),
        )
        if isinstance(item.source_platform, SourcePlatform)
        else (
            item.adapter_id,
            item.parser_version,
            item.registry_version,
            item.rules_version,
        )
    )
    return _digest(
        [
            item.sha256,
            item.display_path,
            item.source_platform,
            item.adapter_version,
            *source_versions,
            GRAPH_VERSION,
            REGISTRY_VERSION,
            RULES_VERSION,
            ASSESSMENT_RULES_VERSION,
            COMPILER_VERSION,
            ETL_COMPILER_VERSION,
            IR_VERSION,
            CAPACITY_MODEL_VERSION,
            SUPPORT_TABLE_FINGERPRINT,
        ]
    )


def neutral_cache_key(item: WorkflowCandidateResponse) -> str:
    """Key for the target-neutral assessment of one confirmed file."""
    return "neutral:" + _digest(
        [
            item.sha256,
            item.display_path,
            item.source_platform,
            item.adapter_id,
            item.adapter_version,
            item.parser_version,
            item.registry_version,
            item.rules_version,
            GRAPH_VERSION,
            IR_VERSION,
            EXTENSIBLE_SOURCE_IR_VERSION,
            NEUTRAL_ASSESSMENT_VERSION,
        ]
    )
