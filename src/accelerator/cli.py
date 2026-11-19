"""Command-line entry point."""

import json
from pathlib import Path
from typing import Annotated, Literal

import typer
import uvicorn

from accelerator.application import AssessmentApplication
from accelerator.discovery import InputRejectedError
from accelerator.generation import Target
from accelerator.runs import RunService

app = typer.Typer(no_args_is_help=True)


@app.callback()
def main() -> None:
    """Assess and migrate Alteryx workflows to Microsoft Fabric."""


@app.command()
def assess(
    path: Annotated[Path, typer.Argument(exists=True, readable=True, resolve_path=True)],
) -> None:
    """Assess workflows found under PATH."""
    try:
        summary = AssessmentApplication().assess(path)
    except InputRejectedError as error:
        typer.echo(
            json.dumps(
                {"path": error.path, "reason": error.reason, "message": error.detail},
                sort_keys=True,
            ),
            err=True,
        )
        raise typer.Exit(code=2) from error
    typer.echo(summary.model_dump_json(indent=2))
    if summary.failed_count:
        raise typer.Exit(code=1)


@app.command()
def preview(
    path: Annotated[Path, typer.Argument(exists=True, readable=True)],
) -> None:
    """Preview workflows before assessment without parsing them."""
    try:
        result = AssessmentApplication().preview(path)
    except InputRejectedError as error:
        typer.echo(str(error), err=True)
        raise typer.Exit(code=2) from error
    typer.echo(result.model_dump_json(indent=2))


@app.command()
def serve(port: Annotated[int, typer.Option(min=1024, max=65535)] = 8050) -> None:
    """Serve the built analyst UI and API together, on loopback only."""
    uvicorn.run("accelerator.api:app", host="127.0.0.1", port=port)


@app.command()
def desktop(
    debug: Annotated[
        bool,
        typer.Option(help="Enable the embedded WebView developer tools"),
    ] = False,
    smoke_test: Annotated[
        bool,
        typer.Option("--smoke-test", hidden=True, help="Verify startup without opening a window"),
    ] = False,
) -> None:
    """Open the accelerator as a native Windows desktop utility."""
    from accelerator.desktop import launch_desktop

    try:
        launch_desktop(debug=debug, smoke_test=smoke_test)
    except (FileNotFoundError, OSError, RuntimeError, TimeoutError) as error:
        typer.echo(str(error), err=True)
        raise typer.Exit(code=1) from error


@app.command("generate")
def generate_artifacts(
    run_id: Annotated[str, typer.Argument(help="Completed local run ID")],
    target: Annotated[
        Literal["notebook", "dataflow", "pipeline", "both", "all"],
        typer.Option(help="Fabric definition type to generate"),
    ] = "both",
    output: Annotated[Path, typer.Option(help="Project output directory")] = Path(
        "generated-fabric-workflows"
    ),
) -> None:
    """Persist Fabric definition files for a completed assessment run."""
    try:
        with RunService(Path(".accelerator"), artifact_root=output) as service:
            if target == "all":
                targets: tuple[Target, ...] = ("notebook", "dataflow", "pipeline")
            elif target == "both":
                targets = ("notebook", "dataflow")
            else:
                targets = (target,)
            results = []
            for item_target in targets:
                result = service.write_artifacts(run_id, item_target)
                results.append(
                    {
                        "target": item_target,
                        "path": str(result.root.resolve()),
                        "generated": sum(item.definition_ready for item in result.candidates),
                        "blocked": sum(not item.definition_ready for item in result.candidates),
                    }
                )
            typer.echo(json.dumps({"run_id": run_id, "results": results}, indent=2))
    except (KeyError, OSError, ValueError) as error:
        typer.echo(str(error), err=True)
        raise typer.Exit(code=2) from error
