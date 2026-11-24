"""Immutable snapshot staging and tiered integrity verification."""

from __future__ import annotations

import logging
import tempfile
import time
from dataclasses import replace
from pathlib import Path

from accelerator.runtime.identity import copy_with_sha256, sha256_file, snapshot_id
from accelerator.runtime.models import SnapshotPreview
from accelerator.runtime.store import RunStore
from etl_migration_core.contracts.ir import SourcePlatform
from etl_migration_core.intake.archive import hash_idmc_directory
from etl_migration_core.intake.discovery import DiscoveryService
from etl_migration_core.intake.schemas import SkippedItemResponse, WorkflowCandidateResponse
from etl_migration_core.sources.registry import SourceAdapterRegistry

logger = logging.getLogger(__name__)


class SnapshotManager:
    """Stage immutable workflow snapshots and verify file & adapter provenance."""

    def __init__(
        self,
        root: Path,
        store: RunStore,
        discovery: DiscoveryService,
        source_registry: SourceAdapterRegistry,
    ) -> None:
        self._root = root
        self._store = store
        self._discovery = discovery
        self._source_registry = source_registry

    def preview(self, source: Path) -> SnapshotPreview:
        """Discover, atomically stage, hash-verify, and record a snapshot preview."""
        started = time.perf_counter()
        summary = self._discovery.discover(source)
        snap_id = snapshot_id(summary.workflows)
        folder = self._root / "snapshots" / snap_id
        folder.mkdir(parents=True, exist_ok=True)
        files: list[WorkflowCandidateResponse] = []
        for index, candidate in enumerate(summary.workflows):
            destination = folder / f"{index}{candidate.extension}"
            if not destination.exists():
                with tempfile.TemporaryDirectory(dir=folder) as temporary:
                    staging = Path(temporary) / "snapshot"
                    with self._discovery.staged_workflow(candidate) as original:
                        staged_sha256 = (
                            hash_idmc_directory(original, destination=staging)[0]
                            if original.is_dir()
                            else copy_with_sha256(original, staging)
                        )
                    if staged_sha256 != candidate.sha256:
                        raise ValueError(
                            "Source changed during preview; review the selection again"
                        )
                    try:
                        staging.replace(destination)
                    except OSError:
                        if (
                            not destination.exists()
                            or sha256_file(destination) != candidate.sha256
                        ):
                            raise
            elif sha256_file(destination) != candidate.sha256:
                raise ValueError("Source changed during preview; review the selection again")
            files.append(
                WorkflowCandidateResponse.model_validate(
                    replace(
                        candidate, source_path=str(destination), archive_path=None, archive_chain=()
                    )
                )
            )
        preview = SnapshotPreview(
            input_path=summary.input_path,
            input_kind=summary.input_kind,
            workflow_count=summary.workflow_count,
            skipped_count=summary.skipped_count,
            total_size_bytes=summary.total_size_bytes,
            skipped=[SkippedItemResponse.model_validate(item) for item in summary.skipped],
            workflows=files,
            snapshot_id=snap_id,
        )
        with self._store.connection() as connection:
            connection.execute(
                """INSERT INTO snapshots (id, preview, created_at) VALUES (?, ?, ?)
                ON CONFLICT(id) DO UPDATE SET
                    preview=excluded.preview, created_at=excluded.created_at""",
                (snap_id, preview.model_dump_json(), time.time()),
            )
        logger.info(
            "Snapshot %s: %d workflows, %d skipped, %.0f ms",
            snap_id[:12],
            preview.workflow_count,
            preview.skipped_count,
            (time.perf_counter() - started) * 1000,
        )
        return preview

    def load(self, snap_id: str, *, verify_files: bool = True) -> SnapshotPreview:
        """Load a snapshot, always checking engine versions and optionally hashing all files."""
        with self._store.connection() as connection:
            row = connection.execute(
                "SELECT preview FROM snapshots WHERE id=?", (snap_id,)
            ).fetchone()
        if row is None:
            raise KeyError("Snapshot not found; review the selection again")
        preview = SnapshotPreview.model_validate_json(row["preview"])
        if snapshot_id(preview.workflows) != snap_id:
            raise ValueError("Snapshot engine versions changed; review the selection again")
        if verify_files:
            for item in preview.workflows:
                self.verify_item(item)
        return preview

    def verify_item(self, item: WorkflowCandidateResponse) -> None:
        """Verify one staged workflow file's digest and (for plugins) adapter version metadata."""
        path = Path(item.source_path)
        if sha256_file(path) != item.sha256:
            raise ValueError("Confirmed snapshot changed; review the selection again")
        if not isinstance(item.source_platform, SourcePlatform):
            detected = self._source_registry.detect(path, item.display_path)
            if (
                detected.adapter.adapter_id != item.adapter_id
                or detected.match.platform != item.source_platform
                or detected.adapter.adapter_version != item.adapter_version
                or not all((item.parser_version, item.registry_version, item.rules_version))
                or detected.adapter.parser_version != item.parser_version
                or detected.adapter.registry_version != item.registry_version
                or detected.adapter.rules_version != item.rules_version
            ):
                raise ValueError("Confirmed source adapter changed; review the selection again")
