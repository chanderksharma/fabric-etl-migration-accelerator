"""Tests for the secure input boundary."""

import shutil
from pathlib import Path
from typing import NoReturn
from zipfile import ZIP_DEFLATED, ZipFile

import pytest

from etl_migration_core.intake.discovery import DiscoveryService, InputRejectedError
from etl_migration_core.intake.domain import DiscoveryLimits, SkipReason


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


def test_extracted_idmc_obeys_directory_size_and_entry_limits(tmp_path: Path) -> None:
    source = tmp_path / "export"
    shutil.copytree(Path(__file__).parent / "fixtures" / "idmc" / "basic_export", source)

    for limits, reason in (
        (DiscoveryLimits(max_archive_entries=1), SkipReason.ARCHIVE_ENTRY_LIMIT),
        (DiscoveryLimits(max_archive_uncompressed_bytes=1), SkipReason.ARCHIVE_SIZE_LIMIT),
        (DiscoveryLimits(max_file_bytes=1), SkipReason.FILE_TOO_LARGE),
    ):
        with pytest.raises(InputRejectedError) as caught:
            DiscoveryService(limits).discover(source)
        assert caught.value.reason == reason


def test_extracted_idmc_rejects_symbolic_links(tmp_path: Path) -> None:
    source = tmp_path / "export"
    shutil.copytree(Path(__file__).parent / "fixtures" / "idmc" / "basic_export", source)
    link = source / "linked.json"
    try:
        link.symlink_to(source / "manifest.json")
    except OSError:
        pytest.skip("Creating symbolic links is unavailable on this system")
    with pytest.raises(InputRejectedError) as caught:
        DiscoveryService().discover(source)
    assert caught.value.reason == SkipReason.SYMBOLIC_LINK


def test_oversized_xml_is_rejected_before_probe(tmp_path: Path) -> None:
    source = tmp_path / "large.xml"
    source.write_bytes(b"<POWERMART>" + b"x" * 100)

    summary = DiscoveryService(DiscoveryLimits(max_file_bytes=10)).discover(source)

    assert summary.workflow_count == 0
    assert summary.skipped[0].reason == SkipReason.FILE_TOO_LARGE


def test_unreadable_xml_is_reported_as_skipped(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    source = tmp_path / "unreadable.xml"
    source.write_bytes(b"<POWERMART>")

    def fail_open(*args: object, **kwargs: object) -> NoReturn:
        raise PermissionError("not readable")

    monkeypatch.setattr(Path, "open", fail_open)
    summary = DiscoveryService().discover(source)

    assert summary.workflow_count == 0
    assert summary.skipped[0].reason == SkipReason.UNREADABLE_INPUT
