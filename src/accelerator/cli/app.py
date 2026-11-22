"""Command-line entry point."""

import json
from dataclasses import replace
from pathlib import Path
from typing import Annotated, Literal

import typer

from accelerator.runtime.runs import RunService
from accelerator.settings import DEFAULT_STATE_DIR, Settings, configure_logging
from accelerator.targets import create_default_target_registry
from etl_migration_core.host import PluginHost
from etl_migration_core.intake.discovery import InputRejectedError
from etl_migration_core.sources.defaults import create_default_registry
from etl_portfolio_assessment.service.application import PortfolioAssessmentApplication
from etl_target_fabric.assessment.portfolio import (
    FabricAssessmentApplication as AssessmentApplication,
)
from etl_target_fabric.compilers.alteryx import Target

app = typer.Typer(no_args_is_help=True)

StateDirOption = Annotated[
    Path,
    typer.Option(
        "--state-dir",
        envvar="ACCELERATOR_STATE_DIR",
        help="Run state directory shared with the local API and portal",
    ),
]


def _open_service(state_dir: Path, artifact_dir: Path | None = None) -> RunService:
    """Open the run service with the same settings the API uses."""
    settings = Settings.from_environment()
    return RunService.from_settings(
        replace(settings, state_dir=state_dir, artifact_dir=artifact_dir or settings.artifact_dir)
    )


@app.callback()
def main() -> None:
    """Assess and migrate Alteryx workflows to Microsoft Fabric."""
    configure_logging(Settings.from_environment())


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


@app.command("assess-neutral")
def assess_neutral(
    path: Annotated[Path, typer.Argument(exists=True, readable=True, resolve_path=True)],
) -> None:
    """Assess source assets without selecting a target platform."""
    try:
        summary = PortfolioAssessmentApplication().assess_neutral(path)
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
    if not summary.workflows:
        typer.echo("No supported workflows were found.", err=True)
        raise typer.Exit(code=1)
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
    import uvicorn

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
    from accelerator.desktop.window import launch_desktop

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
    output: Annotated[
        Path,
        typer.Option(
            envvar="ACCELERATOR_ARTIFACT_DIR",
            help="Project output directory",
        ),
    ] = Path("generated-fabric-workflows"),
    state_dir: StateDirOption = DEFAULT_STATE_DIR,
) -> None:
    """Persist Fabric definition files for a completed assessment run."""
    try:
        with _open_service(state_dir, output) as service:
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


@app.command("publish")
def publish_artifacts(
    run_id: Annotated[str, typer.Argument(help="Completed local run ID")],
    state_dir: StateDirOption = DEFAULT_STATE_DIR,
) -> None:
    """Publish a content-addressed local artifact set without dispatching deployment."""
    try:
        with _open_service(state_dir) as service:
            publication = service.publish_artifacts(run_id)
        typer.echo(publication.model_dump_json(indent=2))
    except (KeyError, OSError, ValueError) as error:
        typer.echo(str(error), err=True)
        raise typer.Exit(code=2) from error


@app.command("verify-publication")
def verify_publication(
    run_id: Annotated[str, typer.Argument(help="Completed local run ID")],
    digest: Annotated[str, typer.Argument(help="Publication SHA-256 digest")],
    state_dir: StateDirOption = DEFAULT_STATE_DIR,
) -> None:
    """Verify a local publication manifest and its artifact files."""
    try:
        with _open_service(state_dir) as service:
            publication = service.verify_publication(run_id, digest)
        typer.echo(publication.model_dump_json(indent=2))
    except (KeyError, OSError, ValueError) as error:
        typer.echo(str(error), err=True)
        raise typer.Exit(code=2) from error


@app.command("gc")
def collect_garbage(
    state_dir: StateDirOption = DEFAULT_STATE_DIR,
    max_age_days: Annotated[
        float, typer.Option(min=0, help="Delete finished runs and unused snapshots older than this")
    ] = 30,
    max_cache_mib: Annotated[
        int, typer.Option(min=0, help="Evict the coldest cache entries above this size")
    ] = 512,
    dry_run: Annotated[bool, typer.Option(help="Report what would be deleted")] = False,
) -> None:
    """Apply the retention policy to local runs, snapshots, publications, and caches.

    Stop the portal first. Queued and running runs, and the snapshots they use, are kept.
    """
    try:
        with _open_service(state_dir) as service:
            report = service.collect_garbage(
                max_age_days=max_age_days,
                max_cache_bytes=max_cache_mib * 1024 * 1024,
                dry_run=dry_run,
            )
        typer.echo(report.model_dump_json(indent=2))
    except (OSError, ValueError) as error:
        typer.echo(str(error), err=True)
        raise typer.Exit(code=2) from error


@app.command("targets")
def list_targets() -> None:
    """List registered migration target platforms and capability status."""
    registry = create_default_target_registry(
        plugin_allowlist=Settings.from_environment().plugin_allowlist
    )
    catalog = registry.catalog()
    typer.echo(
        json.dumps(
            {
                "targets": [info.model_dump(mode="json") for info in catalog.targets],
                "faults": [fault.model_dump(mode="json") for fault in catalog.faults],
                "plugins": [item.model_dump(mode="json") for item in registry.plugin_results],
            },
            indent=2,
        )
    )


@app.command("plugins")
def list_plugins() -> None:
    """Show installed source adapters, target providers, and plugin load results.

    Exits with code 1 when an installed plugin failed to load, so CI can gate on it.
    """
    settings = Settings.from_environment()
    host = PluginHost(
        create_default_registry(plugin_allowlist=settings.plugin_allowlist),
        create_default_target_registry(plugin_allowlist=settings.plugin_allowlist),
        allowlist=settings.plugin_allowlist,
    )
    catalog = host.catalog()
    typer.echo(catalog.model_dump_json(indent=2))
    if catalog.failed_count:
        raise typer.Exit(code=1)
