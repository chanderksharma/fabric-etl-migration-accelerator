"""Integrity checks for source-platform parser fixtures."""

import json
from pathlib import Path

from defusedxml import ElementTree

FIXTURES = Path(__file__).parent / "fixtures"


def test_powercenter_fixture_contains_mapping_and_workflow_layers() -> None:
    root = ElementTree.parse(FIXTURES / "powercenter" / "basic_repository.xml").getroot()

    assert root is not None
    assert root.tag == "POWERMART"
    assert root.get("REPOSITORY_VERSION") == "10.5"
    assert root.find(".//MAPPING[@NAME='m_orders']") is not None
    assert root.find(".//SESSION[@NAME='s_orders']") is not None
    assert root.find(".//WORKFLOW[@NAME='wf_orders']") is not None
    assert root.find(".//WORKFLOWLINK") is not None


def test_idmc_fixture_manifest_resolves_every_asset_directory() -> None:
    root = FIXTURES / "idmc" / "basic_export"
    manifest = json.loads((root / "manifest.json").read_text(encoding="utf-8"))

    assert manifest["exportVersion"] == "3"
    assert {asset["type"] for asset in manifest["assets"]} == {
        "DTEMPLATE",
        "MTT",
        "TASKFLOW",
    }
    for asset in manifest["assets"]:
        directory = root / Path(asset["path"])
        metadata = json.loads((directory / "metadata.json").read_text(encoding="utf-8"))
        assert metadata["name"] == asset["name"]
        assert metadata["type"] == asset["type"]


def test_source_fixtures_contain_no_credential_fields() -> None:
    forbidden = ("password", "secret", "token", "accountkey")

    for path in FIXTURES.rglob("*"):
        if not path.is_file():
            continue
        content = path.read_text(encoding="utf-8").casefold()
        assert not any(marker in content for marker in forbidden), path

