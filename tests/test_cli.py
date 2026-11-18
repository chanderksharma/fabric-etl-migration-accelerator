"""CLI contract tests."""

import json
from pathlib import Path

import pytest
from typer.testing import CliRunner

from accelerator.cli import app
from accelerator.runs import RunService


def test_preview_subcommand_returns_discovery_summary(tmp_path: Path) -> None:
    (tmp_path / "sample.yxmd").write_text("<Workflow />", encoding="utf-8")

    result = CliRunner().invoke(app, ["preview", str(tmp_path)])

    assert result.exit_code == 0
    body = json.loads(result.stdout)
    assert body["workflow_count"] == 1
    assert body["workflows"][0]["display_path"] == "sample.yxmd"


def test_generate_command_persists_fabric_definitions(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    source = tmp_path / "sample.yxmd"
    source.write_text(
        """<AlteryxDocument><Nodes>
        <Node ToolID="1"><GuiSettings Plugin="AlteryxBasePluginsGui.TextInput.TextInput"/>
        <Properties><Configuration><Fields><Field name="Value"/></Fields>
        <Data><r><c>1</c></r></Data></Configuration></Properties></Node>
        </Nodes></AlteryxDocument>""",
        encoding="utf-8",
    )
    state = tmp_path / ".accelerator"
    service = RunService(state)
    run = service.create_run(service.preview(source).snapshot_id)
    service.execute(run.id)
    service.close()
    monkeypatch.chdir(tmp_path)

    result = CliRunner().invoke(
        app,
        [
            "generate",
            run.id,
            "--target",
            "both",
            "--output",
            "generated-fabric-workflows",
        ],
    )

    assert result.exit_code == 0
    workflow = tmp_path / "generated-fabric-workflows" / "sample"
    assert (workflow / "notebook-content.ipynb").is_file()
    assert (workflow / "dataflow-mashup.pq").is_file()
