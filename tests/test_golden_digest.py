"""Golden digest for the synthetic sample estate.

This does not regenerate ``generated-fabric-workflows/``. Acceptance tests read that
committed deployment sample. The digest covers a fresh write of ``alteryx-workflows``
plus the PowerCenter fixtures, with the run id and host path separators masked.
"""

from __future__ import annotations

import hashlib
import json
import shutil
import tempfile
from pathlib import Path

from accelerator.runtime.runs import RunService

ROOT = Path(__file__).parents[1]
DIGEST_PATH = ROOT / "tests" / "fixtures" / "golden" / "sample-estate-digest.json"
_RUN_MASK = "0" * 32
_PROTECTED = "\u0001"
_BACKSLASH = chr(92)


def _normalize_artifact(payload: bytes, run_id: str) -> bytes:
    """Mask the run id and Windows display-path separators without rewriting code escapes."""
    text = payload.replace(run_id.encode("ascii"), _RUN_MASK.encode("ascii")).decode("utf-8")
    protected = text.replace(_BACKSLASH * 4, _PROTECTED)
    restored = protected.replace(_BACKSLASH * 2, "/").replace(_PROTECTED, _BACKSLASH * 4)
    return restored.encode("utf-8")


def _masked_files(root: Path, run_id: str) -> list[dict[str, str]]:
    rows = []
    for path in sorted(item for item in root.rglob("*") if item.is_file()):
        digest = hashlib.sha256(_normalize_artifact(path.read_bytes(), run_id)).hexdigest()
        rows.append({"path": path.relative_to(root).as_posix(), "sha256": digest})
    return rows


def _sample_digest(tmp_path: Path) -> dict[str, object]:
    source = tmp_path / "input"
    shutil.copytree(ROOT / "alteryx-workflows", source / "alteryx-workflows")
    shutil.copytree(ROOT / "tests" / "fixtures" / "powercenter", source / "powercenter")
    artifacts = tmp_path / "artifacts"
    with RunService(tmp_path / "state", artifact_root=artifacts) as service:
        preview = service.preview(source)
        run = service.create_run(preview.snapshot_id)
        service.execute(run.id)
        finished = service.get_run(run.id)
        if finished.status != "completed":
            raise AssertionError(f"sample estate assessment did not complete: {finished.status}")
        service.write_all_artifacts(run.id)
        files = _masked_files(artifacts, run.id)
    return {
        "workflow_count": preview.workflow_count,
        "targets": ["dataflow", "notebook", "pipeline"],
        "mask": ["run_id", "host-path-separator"],
        "files": files,
    }


def _file_map(payload: dict[str, object]) -> dict[str, str]:
    files = payload["files"]
    if not isinstance(files, list):
        raise TypeError("digest files must be a list")
    mapped: dict[str, str] = {}
    for item in files:
        if not isinstance(item, dict):
            raise TypeError("digest file entry must be an object")
        mapped[str(item["path"])] = str(item["sha256"])
    return mapped


def _difference(expected: dict[str, object], actual: dict[str, object]) -> str:
    expected_files = _file_map(expected)
    actual_files = _file_map(actual)
    lines: list[str] = []
    if expected.get("workflow_count") != actual.get("workflow_count"):
        lines.append(
            f"workflow_count {actual.get('workflow_count')} != {expected.get('workflow_count')}"
        )
    missing = sorted(set(expected_files) - set(actual_files))
    extra = sorted(set(actual_files) - set(expected_files))
    changed = sorted(
        path
        for path in set(expected_files) & set(actual_files)
        if expected_files[path] != actual_files[path]
    )
    if missing:
        lines.append("missing: " + ", ".join(missing[:8]))
    if extra:
        lines.append("extra: " + ", ".join(extra[:8]))
    if changed:
        lines.append("changed: " + ", ".join(changed[:8]))
    return "\n".join(lines)


def test_digest_normalizer_masks_run_id_and_host_separators() -> None:
    run_id = "ab" * 16
    pair = _BACKSLASH * 2
    quad = _BACKSLASH * 4
    payload = (
        f'{{"run_id": "{run_id}", "workflow": "powercenter{pair}wf.xml", '
        f'"code": "not in {quad}"}}'
    ).encode()
    normalized = _normalize_artifact(payload, run_id).decode("utf-8")
    assert run_id not in normalized
    assert _RUN_MASK in normalized
    assert "powercenter/wf.xml" in normalized
    assert quad in normalized


def test_sample_estate_digest_matches_the_golden_fixture(tmp_path: Path) -> None:
    actual = _sample_digest(tmp_path)
    expected = json.loads(DIGEST_PATH.read_text(encoding="utf-8"))
    assert actual["workflow_count"] == 17
    assert not _difference(expected, actual), _difference(expected, actual)


def main() -> int:
    """Refresh the fixture after an intentional compiler change. Not used by pytest."""
    with tempfile.TemporaryDirectory(prefix="golden-refresh-") as directory:
        payload = _sample_digest(Path(directory))
    DIGEST_PATH.parent.mkdir(parents=True, exist_ok=True)
    DIGEST_PATH.write_text(json.dumps(payload, indent=2) + "\n", encoding="utf-8")
    print(
        f"wrote {DIGEST_PATH} workflows={payload['workflow_count']} "
        f"files={len(_file_map(payload))}"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
