"""Tests for the secure input boundary."""

from pathlib import Path
from zipfile import ZIP_DEFLATED, ZipFile

import pytest

from accelerator.discovery import DiscoveryService, InputRejectedError
from accelerator.domain import DiscoveryLimits, SkipReason


def test_folder_discovery_is_recursive_deduplicated_and_deterministic(tmp_path: Path) -> None:
    nested = tmp_path / "nested"
    nested.mkdir()
    (tmp_path / "first.yxmd").write_text("<Workflow />", encoding="utf-8")
    (nested / "duplicate.yxmc").write_text("<Workflow />", encoding="utf-8")
    (nested / "second.YXWZ").write_text("<Wizard />", encoding="utf-8")
    (nested / "notes.txt").write_text("skip", encoding="utf-8")

    summary = DiscoveryService().discover(tmp_path)

    assert [item.display_path for item in summary.workflows] == [
        "first.yxmd",
        str(Path("nested") / "second.YXWZ"),
    ]
    assert [item.reason for item in summary.skipped] == [
        SkipReason.DUPLICATE_CONTENT,
        SkipReason.UNSUPPORTED_EXTENSION,
    ]
    assert summary.total_size_bytes == len("<Workflow />") + len("<Wizard />")


def test_zip_path_traversal_is_rejected(tmp_path: Path) -> None:
    archive = tmp_path / "malicious.zip"
    with ZipFile(archive, "w") as package:
        package.writestr("../escape.yxmd", "<Workflow />")

    with pytest.raises(InputRejectedError) as caught:
        DiscoveryService().discover(archive)

    assert caught.value.reason is SkipReason.ARCHIVE_PATH_TRAVERSAL


def test_zip_compression_ratio_is_rejected(tmp_path: Path) -> None:
    archive = tmp_path / "bomb.zip"
    with ZipFile(archive, "w", compression=ZIP_DEFLATED) as package:
        package.writestr("large.yxmd", "0" * 100_000)

    service = DiscoveryService(DiscoveryLimits(max_compression_ratio=2.0))
    with pytest.raises(InputRejectedError) as caught:
        service.discover(archive)

    assert caught.value.reason is SkipReason.ARCHIVE_RATIO_LIMIT


def test_staged_zip_is_removed_after_context_exit(tmp_path: Path) -> None:
    archive = tmp_path / "workflows.zip"
    with ZipFile(archive, "w") as package:
        package.writestr("nested/workflow.yxmd", "<Workflow />")

    sandbox: Path
    with DiscoveryService().staged_zip(archive) as sandbox:
        assert (sandbox / "nested" / "workflow.yxmd").is_file()
        extracted_root = sandbox

    assert not extracted_root.exists()


def test_zip_discovery_reports_supported_skipped_and_duplicate_entries(tmp_path: Path) -> None:
    archive = tmp_path / "workflows.zip"
    with ZipFile(archive, "w") as package:
        package.writestr("a/workflow.yxmd", "<Workflow />")
        package.writestr("b/duplicate.yxmc", "<Workflow />")
        package.writestr("notes/readme.txt", "skip")

    summary = DiscoveryService().discover(archive)

    assert summary.workflow_count == 1
    assert summary.workflows[0].archive_path == "a/workflow.yxmd"
    assert [item.reason for item in summary.skipped] == [
        SkipReason.DUPLICATE_CONTENT,
        SkipReason.UNSUPPORTED_EXTENSION,
    ]
