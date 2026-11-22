"""Content-addressed local publications: manifests, verification, and deterministic archives."""

from __future__ import annotations

import hashlib
import io
import json
import zipfile
from pathlib import Path
from typing import Literal, TypedDict

from accelerator.runtime.identity import sha256_file

MANIFEST_NAME = "publication-manifest.json"
_ZIP_EPOCH = (1980, 1, 1, 0, 0, 0)


class PublicationFile(TypedDict):
    path: str
    size_bytes: int
    sha256: str


class PublicationManifest(TypedDict):
    version: Literal[1]
    run_id: str
    files: list[PublicationFile]


def build_manifest(root: Path, identity: str) -> PublicationManifest:
    """List every regular file under ``root`` with its size and digest, rejecting links."""
    files: list[PublicationFile] = []
    for path in sorted(root.rglob("*"), key=lambda item: item.relative_to(root).as_posix()):
        if path.is_symlink() or path.is_junction():
            raise ValueError("Artifact publication contains a linked path")
        if path.is_dir():
            continue
        if not path.is_file():
            raise ValueError("Artifact publication contains a non-file entry")
        relative = path.relative_to(root).as_posix()
        if relative == MANIFEST_NAME:
            continue
        files.append(
            {
                "path": relative,
                "size_bytes": path.stat().st_size,
                "sha256": sha256_file(path),
            }
        )
    return {"version": 1, "run_id": identity, "files": files}


def read_manifest(root: Path) -> dict[str, object]:
    """Read the recorded manifest of a publication directory."""
    if root.is_symlink() or root.is_junction():
        raise ValueError("Artifact publication contains a linked path")
    manifest_path = root / MANIFEST_NAME
    if manifest_path.is_symlink() or manifest_path.is_junction():
        raise ValueError("Artifact publication contains a linked path")
    try:
        recorded = json.loads(manifest_path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as error:
        raise ValueError("Artifact publication manifest is unavailable or invalid") from error
    if not isinstance(recorded, dict) or recorded.get("version") != 1:
        raise ValueError("Artifact publication manifest is invalid")
    return recorded


def manifest_bytes(manifest: PublicationManifest | dict[str, object]) -> bytes:
    """Canonical manifest encoding; its SHA-256 is the publication digest."""
    return json.dumps(manifest, sort_keys=True, separators=(",", ":")).encode("utf-8")


def manifest_digest(manifest: PublicationManifest | dict[str, object]) -> str:
    return hashlib.sha256(manifest_bytes(manifest)).hexdigest()


def check_tree(root: Path, expected: PublicationManifest | dict[str, object]) -> None:
    """Fail unless the recorded manifest and the files on disk both match ``expected``."""
    recorded = read_manifest(root)
    if manifest_bytes(recorded) != manifest_bytes(expected) or manifest_bytes(
        build_manifest(root, str(expected["run_id"]))
    ) != manifest_bytes(expected):
        raise ValueError("Artifact publication has changed; refusing to overwrite it")


def build_archive(root: Path, manifest: PublicationManifest) -> bytes:
    """Package only manifest-listed files, re-checking each against its recorded digest."""
    output = io.BytesIO()
    with zipfile.ZipFile(output, "w") as archive:
        for entry in manifest["files"]:
            content = (root / entry["path"]).read_bytes()
            if len(content) != entry["size_bytes"] or (
                hashlib.sha256(content).hexdigest() != entry["sha256"]
            ):
                raise ValueError("Artifact publication has changed while packaging")
            _add(archive, entry["path"], content)
        manifest_content = (root / MANIFEST_NAME).read_bytes()
        if json.loads(manifest_content) != manifest:
            raise ValueError("Artifact publication has changed while packaging")
        _add(archive, MANIFEST_NAME, manifest_content)
    return output.getvalue()


def _add(archive: zipfile.ZipFile, name: str, content: bytes) -> None:
    info = zipfile.ZipInfo(name, date_time=_ZIP_EPOCH)
    info.compress_type = zipfile.ZIP_DEFLATED
    archive.writestr(info, content)
