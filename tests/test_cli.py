"""CLI contract tests."""

import json
from pathlib import Path

import pytest
from typer.testing import CliRunner

from accelerator.cli.app import app
from accelerator.runtime.runs import RunService


def test_preview_subcommand_returns_discovery_summary(tmp_path: Path) -> None:
    (tmp_path / "sample.yxmd").write_text("<Workflow />", encoding="utf-8")

    result = CliRunner().invoke(app, ["preview", str(tmp_path)])

    assert result.exit_code == 0
    body = json.loads(result.stdout)
    assert body["workflow_count"] == 1
    assert body["workflows"][0]["display_path"] == "sample.yxmd"


def test_desktop_subcommand_is_available() -> None:
    result = CliRunner().invoke(app, ["desktop", "--help"])

    assert result.exit_code == 0
    assert "native Windows desktop utility" in result.stdout


def test_neutral_assessment_reports_missing_and_invalid_workflows(tmp_path: Path) -> None:
    runner = CliRunner()
    empty = runner.invoke(app, ["assess-neutral", str(tmp_path)])
    assert empty.exit_code == 1
    assert "No supported workflows were found." in empty.output

    (tmp_path / "bad.yxmd").write_text("<not-xml", encoding="utf-8")
    invalid = runner.invoke(app, ["assess-neutral", str(tmp_path)])
    assert invalid.exit_code == 1
    assert json.loads(invalid.stdout)["failed_count"] == 1


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


def test_publish_and_verify_commands_detect_changed_artifacts(
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
    with RunService(tmp_path / ".accelerator") as service:
        run = service.create_run(service.preview(source).snapshot_id)
        service.execute(run.id)
    monkeypatch.chdir(tmp_path)
    runner = CliRunner()
    published = runner.invoke(app, ["publish", run.id])
    assert published.exit_code == 0, published.output
    result = json.loads(published.stdout)
    root = Path(result["root"])
    verified = runner.invoke(app, ["verify-publication", run.id, result["digest"]])
    assert verified.exit_code == 0, verified.output
    assert json.loads(verified.stdout)["root"] == str(root)

    (root / "sample" / "notebook-manifest.json").write_text("changed", encoding="utf-8")
    rejected = runner.invoke(app, ["verify-publication", run.id, result["digest"]])
    assert rejected.exit_code == 2
    assert "publication has changed" in rejected.output
