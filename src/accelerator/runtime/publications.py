"""Content-addressed publication lifecycle service."""

from __future__ import annotations

import hashlib
import json
import re
import tempfile
from collections.abc import Callable
from pathlib import Path

from accelerator.runtime.models import ArtifactPublication
from accelerator.runtime.publication import (
    MANIFEST_NAME,
    build_archive,
    build_manifest,
    check_tree,
    manifest_bytes,
    manifest_digest,
    read_manifest,
)

_RUN_ID_PATTERN = re.compile(r"[a-f0-9]{32}")
_DIGEST_PATTERN = re.compile(r"[a-f0-9]{64}")


class PublicationService:
    """Publish, verify, and archive content-addressed artifact trees."""

    def __init__(self, root: Path) -> None:
        self._root = root

    def publish(
        self,
        identity: str,
        *,
        stage_artifacts: Callable[[Path], object],
    ) -> ArtifactPublication:
        """Atomically publish a run's artifacts under ``publications/<run_id>/<digest>``."""
        _require_run_id(identity)
        publications = self._root / "publications"
        parent = publications / identity
        for directory in (publications, parent):
            if directory.is_symlink() or directory.is_junction():
                raise ValueError("Artifact publication contains a linked path")
            directory.mkdir(exist_ok=True)
        with tempfile.TemporaryDirectory(prefix=".staging-", dir=parent) as temporary:
            staging = Path(temporary) / "contents"
            stage_artifacts(staging)
            manifest = build_manifest(staging, identity)
            digest = manifest_digest(manifest)
            (staging / MANIFEST_NAME).write_bytes(manifest_bytes(manifest))
            destination = parent / digest
            try:
                staging.rename(destination)
            except OSError:
                if not destination.is_dir():
                    raise
                check_tree(destination, manifest)
            return ArtifactPublication(run_id=identity, digest=digest, root=destination.resolve())

    def verify(self, identity: str, digest: str) -> ArtifactPublication:
        """Verify a local publication manifest and every listed artifact file."""
        _require_run_id(identity)
        if not _DIGEST_PATTERN.fullmatch(digest):
            raise ValueError(
                "Publication digest must be a 64-character lowercase hexadecimal value"
            )
        publications = self._root / "publications"
        parent = publications / identity
        root = parent / digest
        if any(path.is_symlink() or path.is_junction() for path in (publications, parent, root)):
            raise ValueError("Artifact publication contains a linked path")
        manifest = read_manifest(root)
        if manifest.get("run_id") != identity or manifest_digest(manifest) != digest:
            raise ValueError("Artifact publication manifest does not match its identity")
        check_tree(root, manifest)
        return ArtifactPublication(run_id=identity, digest=digest, root=root.resolve())

    def verify_staged(self, identity: str, digest: str, staged_root: Path) -> str:
        """Compare regenerated artifacts against a publication and return manifest SHA-256."""
        publication = self.verify(identity, digest)
        staged = build_manifest(staged_root, identity)
        if manifest_digest(staged) != digest:
            raise ValueError("Current artifacts do not match the selected publication")
        try:
            content = (publication.root / MANIFEST_NAME).read_bytes()
            recorded = json.loads(content)
        except (OSError, UnicodeDecodeError, json.JSONDecodeError) as error:
            raise ValueError("Artifact publication manifest is unavailable or invalid") from error
        if not isinstance(recorded, dict) or manifest_digest(recorded) != digest:
            raise ValueError("Artifact publication manifest does not match its identity")
        check_tree(publication.root, recorded)
        return hashlib.sha256(content).hexdigest()

    def package(self, identity: str, digest: str) -> bytes:
        """Build a byte-stable ZIP archive of a verified publication."""
        publication = self.verify(identity, digest)
        manifest = build_manifest(publication.root, identity)
        check_tree(publication.root, manifest)
        if manifest_digest(manifest) != digest:
            raise ValueError("Artifact publication has changed while packaging")
        return build_archive(publication.root, manifest)


def _require_run_id(identity: str) -> None:
    if not _RUN_ID_PATTERN.fullmatch(identity):
        raise ValueError("Run ID must be a 32-character lowercase hexadecimal value")
