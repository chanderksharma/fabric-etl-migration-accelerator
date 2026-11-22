"""FastAPI entry point."""

import asyncio
import logging
import os
import secrets
import shutil
import tempfile
import time
from collections.abc import AsyncIterator, Awaitable, Callable
from concurrent.futures import Future, ThreadPoolExecutor
from contextlib import asynccontextmanager, suppress
from pathlib import Path
from typing import Annotated, Literal

from dotenv import load_dotenv
from fastapi import FastAPI, File, Form, HTTPException, Query, Request, UploadFile
from fastapi.responses import HTMLResponse, RedirectResponse, Response
from fastapi.staticfiles import StaticFiles
from pydantic import TypeAdapter
from starlette.concurrency import run_in_threadpool
from starlette.middleware.trustedhost import TrustedHostMiddleware

from accelerator import __version__
from accelerator.delivery.github import (
    GitHubConfigurationError,
    GitHubDeploymentError,
    GitHubDeploymentResult,
    GitHubDeploymentSelection,
    GitHubDeploymentService,
)
from accelerator.delivery.gitlab import (
    GitLabConfigurationError,
    GitLabDeploymentError,
    GitLabDeploymentResult,
    GitLabDeploymentSelection,
    GitLabDeploymentService,
)
from accelerator.delivery.provenance import PublicationDispatch
from accelerator.runtime.runs import (
    Run,
    RunService,
    RunStatus,
    RunTargetEvaluation,
    SnapshotPreview,
)
from accelerator.server.deployment import (
    DeploymentTarget,
    plan_deployment_dispatch,
    resolve_deployment_artifact,
)
from accelerator.server.schemas import (
    Confirmation,
    DevSelection,
    FolderSelectionResponse,
    LocalSelection,
    PluginsResponse,
    PublicationReference,
    SourcesResponse,
    TargetsResponse,
)
from accelerator.server.uploads import stage_uploads
from accelerator.settings import Settings, configure_logging
from accelerator.targets import (
    TargetPlatformRegistry,
    UnknownTargetPlatformError,
    create_default_target_registry,
)
from etl_migration_core.contracts.spi import (
    TargetCapacityResult,
    TargetGenerationResult,
    TargetPlatformInfo,
    UnsupportedTargetCapabilityError,
)
from etl_migration_core.host import PluginHost
from etl_migration_core.intake.discovery import InputRejectedError
from etl_migration_core.sources.alteryx.graph import WorkflowGraph
from etl_portfolio_assessment.evidence.extractor import EvidenceResponse
from etl_portfolio_assessment.service.schemas import NeutralEstateAssessmentResponse
from etl_target_fabric.assessment.portfolio import (
    FabricAssessmentApplication as AssessmentApplication,
)
from etl_target_fabric.assessment.schemas import DiscoverySummaryResponse, EstateAssessmentResponse
from etl_target_fabric.assessment.workflow import REGISTRY_VERSION, RULES_VERSION, registry_entries
from etl_target_fabric.capacity.model import CapacityPortfolioEstimate, CapacityUpdate, capacity_csv
from etl_target_fabric.compilers.alteryx import Candidate, Target
from etl_target_fabric.delivery.deployer import DryRunResult, dry_run

load_dotenv()

logger = logging.getLogger(__name__)
WORKER_RETRY_SECONDS = 5.0


@asynccontextmanager
async def lifespan(api: FastAPI) -> AsyncIterator[None]:
    configure_logging(Settings.from_environment())
    if not hasattr(api.state, "run_service") or api.state.run_service.closed:
        api.state.run_service = _new_run_service()
    executor = ThreadPoolExecutor(max_workers=2, thread_name_prefix="accelerator")
    futures: dict[str, Future[None]] = {}
    retry_after: dict[str, float] = {}

    async def resume_pending() -> None:
        while True:
            try:
                for identity in await run_in_threadpool(api.state.run_service.pending):
                    if (
                        identity not in futures
                        and len(futures) < 2
                        and retry_after.get(identity, 0) <= time.monotonic()
                    ):
                        futures[identity] = executor.submit(api.state.run_service.execute, identity)
                for identity, future in list(futures.items()):
                    if future.done():
                        del futures[identity]
                        if (error := future.exception()) is not None:
                            logger.error("Run %s worker failed", identity, exc_info=error)
                            retry_after[identity] = time.monotonic() + WORKER_RETRY_SECONDS
            except Exception:
                logger.exception("Run worker loop failed; retrying")
                await asyncio.sleep(WORKER_RETRY_SECONDS)
            await asyncio.sleep(0.2)

    worker = asyncio.create_task(resume_pending())
    try:
        yield
    finally:
        worker.cancel()
        with suppress(asyncio.CancelledError, Exception):
            await worker
        await run_in_threadpool(executor.shutdown, wait=True)
        api.state.run_service.close()


app = FastAPI(title="Alteryx to Fabric Accelerator", version=__version__, lifespan=lifespan)
app.add_middleware(TrustedHostMiddleware, allowed_hosts=["127.0.0.1", "localhost"])
app.state.csrf_token = secrets.token_urlsafe(32)
application = AssessmentApplication()
DESKTOP_TOKEN_COOKIE = "accelerator-desktop-token"


@app.middleware("http")
async def local_origin_guard(
    request: Request, call_next: Callable[[Request], Awaitable[Response]]
) -> Response:
    desktop_token = os.getenv("ACCELERATOR_DESKTOP_TOKEN", "").strip()
    if desktop_token:
        header_token = request.headers.get("x-accelerator-desktop-token", "")
        cookie_token = request.cookies.get(DESKTOP_TOKEN_COOKIE, "")
        query_token = request.query_params.get("desktop_token")
        if query_token is not None:
            if (
                request.method != "GET"
                or request.url.path != "/"
                or not secrets.compare_digest(query_token.encode(), desktop_token.encode())
            ):
                return Response("Desktop session token is invalid", status_code=401)
            bootstrap_response = RedirectResponse("/", status_code=307)
            bootstrap_response.set_cookie(
                DESKTOP_TOKEN_COOKIE,
                desktop_token,
                httponly=True,
                samesite="strict",
                path="/",
            )
            return bootstrap_response
        if not (
            secrets.compare_digest(header_token.encode(), desktop_token.encode())
            or secrets.compare_digest(cookie_token.encode(), desktop_token.encode())
        ):
            return Response("Desktop session token is required", status_code=401)
    origin = request.headers.get("origin")
    if origin:
        if origin != f"{request.url.scheme}://{request.headers.get('host')}":
            return Response("Untrusted browser origin", status_code=403)
        if request.method not in {"GET", "HEAD"} and not secrets.compare_digest(
            request.headers.get("x-accelerator-token", "").encode(), app.state.csrf_token.encode()
        ):
            return Response("Browser session token is required", status_code=403)
    response = await call_next(request)
    if request.url.path.startswith("/api/runs"):
        response.headers["Cache-Control"] = "no-store"
    return response


@app.get("/health")
def health() -> dict[str, str]:
    """Return process health."""
    return {"status": "ok", "version": __version__}


@app.get("/api/intake/preview", response_model=DiscoverySummaryResponse)
def preview(path: str = Query(min_length=1)) -> DiscoverySummaryResponse:
    """Preview a local file, ZIP, or folder before assessment."""
    try:
        return application.preview(Path(path))
    except InputRejectedError as error:
        raise HTTPException(
            status_code=400,
            detail={"path": error.path, "reason": error.reason, "message": error.detail},
        ) from error


@app.post("/api/intake/upload", response_model=DiscoverySummaryResponse)
async def upload_preview(
    mode: Annotated[Literal["files", "zip", "folder"], Form()],
    files: Annotated[list[UploadFile], File()],
) -> DiscoverySummaryResponse:
    """Stage browser uploads locally and return the secure pre-run summary."""
    if mode == "zip" and len(files) != 1:
        raise HTTPException(status_code=400, detail="ZIP mode requires exactly one archive")

    sandbox = Path(tempfile.mkdtemp(prefix="alteryx-upload-"))
    try:
        staged = await stage_uploads(files, sandbox)
        target_path = staged[0] if mode == "zip" else sandbox
        return await run_in_threadpool(application.preview, target_path)
    except InputRejectedError as error:
        raise HTTPException(
            status_code=400,
            detail={"path": error.path, "reason": error.reason, "message": error.detail},
        ) from error
    finally:
        shutil.rmtree(sandbox, ignore_errors=False)


@app.post("/api/assessment/upload", response_model=EstateAssessmentResponse)
async def upload_assessment(
    mode: Annotated[Literal["files", "folder", "zip"], Form()],
    files: Annotated[list[UploadFile], File()],
) -> EstateAssessmentResponse:
    """Assess uploaded XML workflows with per-file fault isolation."""
    sandbox = Path(tempfile.mkdtemp(prefix="alteryx-assess-"))
    try:
        if mode == "zip" and len(files) != 1:
            raise HTTPException(status_code=400, detail="ZIP mode requires exactly one archive")
        staged = await stage_uploads(files, sandbox)
        return await run_in_threadpool(application.assess, staged[0] if mode == "zip" else sandbox)
    except InputRejectedError as error:
        raise HTTPException(status_code=400, detail=error.detail) from error
    finally:
        shutil.rmtree(sandbox, ignore_errors=False)


_DIALOG_EXECUTOR = ThreadPoolExecutor(max_workers=1, thread_name_prefix="folder-dialog")


def _pick_local_folder() -> str | None:
    import tkinter as tk
    from tkinter import filedialog

    try:
        root = tk.Tk()
    except tk.TclError as error:
        raise RuntimeError("Native folder picker is unavailable") from error
    try:
        root.withdraw()
        root.attributes("-topmost", True)
        root.lift()
        root.focus_force()
        selected = filedialog.askdirectory(
            parent=root,
            title="Select workflow folder",
            mustexist=True,
        )
    except tk.TclError as error:
        raise RuntimeError("Native folder picker is unavailable") from error
    finally:
        root.destroy()
    return selected or None


def run_service() -> RunService:
    if not hasattr(app.state, "run_service") or app.state.run_service.closed:
        app.state.run_service = _new_run_service()
    service: RunService = app.state.run_service
    return service


def _new_run_service() -> RunService:
    return RunService.from_settings(Settings.from_environment())


@app.get("/api/session")
def browser_session() -> dict[str, str]:
    return {"token": app.state.csrf_token}


@app.get("/api/graph/schema")
def graph_schema() -> dict[str, object]:
    return TypeAdapter(WorkflowGraph).json_schema()


@app.get("/api/registry")
def tool_registry() -> dict[str, object]:
    return {
        "version": REGISTRY_VERSION,
        "rules_version": RULES_VERSION,
        "entries": registry_entries(),
    }


def target_registry() -> TargetPlatformRegistry:
    if not hasattr(app.state, "target_registry"):
        app.state.target_registry = create_default_target_registry(
            plugin_allowlist=Settings.from_environment().plugin_allowlist
        )
    registry: TargetPlatformRegistry = app.state.target_registry
    return registry


def plugin_host(*, with_sources: bool = True) -> PluginHost:
    """Build the plugin view; target-only endpoints skip opening the run store."""
    return PluginHost(
        run_service().source_registry if with_sources else None,
        target_registry(),
        allowlist=Settings.from_environment().plugin_allowlist,
    )


@app.get("/api/sources", response_model=SourcesResponse)
def list_source_adapters() -> SourcesResponse:
    """List registered built-in and plugin source adapters."""
    return SourcesResponse(sources=list(plugin_host().sources()))


@app.get("/api/plugins", response_model=PluginsResponse)
def list_plugins() -> PluginsResponse:
    """Report which installed plugins loaded, failed, or were excluded by the allowlist."""
    catalog = plugin_host().catalog()
    return PluginsResponse(
        allowlist=list(catalog.allowlist) if catalog.allowlist is not None else None,
        failed_count=catalog.failed_count,
        plugins=list(catalog.plugins),
        diagnostics=list(catalog.diagnostics),
    )


@app.get("/api/targets", response_model=TargetsResponse)
def list_target_platforms() -> TargetsResponse:
    host = plugin_host(with_sources=False)
    return TargetsResponse(
        targets=list(host.targets()), faults=list(host.target_catalog().faults)
    )


@app.get("/api/targets/{platform_id}", response_model=TargetPlatformInfo)
def get_target_platform(platform_id: str) -> TargetPlatformInfo:
    try:
        return target_registry().get_info(platform_id)
    except UnknownTargetPlatformError as error:
        raise HTTPException(status_code=404, detail=str(error)) from error
    except ValueError as error:
        raise HTTPException(status_code=409, detail=str(error)) from error


@app.post("/api/snapshots/browse-folder", response_model=FolderSelectionResponse)
async def browse_local_folder() -> FolderSelectionResponse:
    try:
        loop = asyncio.get_running_loop()
        selected = await loop.run_in_executor(_DIALOG_EXECUTOR, _pick_local_folder)
    except (ImportError, RuntimeError, OSError) as error:
        raise HTTPException(
            status_code=501,
            detail="Native folder picker is unavailable in this environment",
        ) from error
    return FolderSelectionResponse(path=selected)


@app.post("/api/snapshots/local", response_model=SnapshotPreview)
def local_snapshot(selection: LocalSelection) -> SnapshotPreview:
    if selection.path.startswith(("\\\\", "//")):
        raise HTTPException(status_code=400, detail="UNC paths are not accepted")
    try:
        return run_service().preview(Path(selection.path))
    except (InputRejectedError, ValueError, OSError) as error:
        raise HTTPException(status_code=400, detail=str(error)) from error


@app.post("/api/snapshots/upload", response_model=SnapshotPreview)
async def uploaded_snapshot(
    mode: Annotated[Literal["files", "zip", "folder"], Form()],
    files: Annotated[list[UploadFile], File()],
) -> SnapshotPreview:
    if mode == "zip" and len(files) != 1:
        raise HTTPException(status_code=400, detail="ZIP mode requires exactly one archive")
    with tempfile.TemporaryDirectory(prefix="alteryx-snapshot-") as directory:
        staged = await stage_uploads(files, Path(directory))
        try:
            return await run_in_threadpool(
                run_service().preview, staged[0] if mode == "zip" else Path(directory)
            )
        except (InputRejectedError, ValueError, OSError) as error:
            raise HTTPException(status_code=400, detail=str(error)) from error


@app.post("/api/runs", response_model=Run, status_code=202)
def confirm_run(confirmation: Confirmation) -> Run:
    try:
        return run_service().create_run(confirmation.snapshot_id)
    except KeyError as error:
        raise HTTPException(status_code=404, detail=str(error)) from error
    except (OSError, ValueError) as error:
        raise HTTPException(status_code=409, detail=str(error)) from error


@app.get("/api/runs/{identity}", response_model=Run)
def get_run(identity: str, include_result: bool = True) -> Run:
    try:
        return run_service().get_run(identity, include_result=include_result)
    except KeyError as error:
        raise HTTPException(status_code=404, detail=str(error)) from error


@app.get("/api/runs/{identity}/status", response_model=RunStatus)
def get_run_status(identity: str) -> RunStatus:
    try:
        return run_service().get_run_status(identity)
    except KeyError as error:
        raise HTTPException(status_code=404, detail=str(error)) from error


@app.get(
    "/api/runs/{identity}/capacity",
    response_model=CapacityPortfolioEstimate,
)
def get_capacity(identity: str) -> CapacityPortfolioEstimate:
    try:
        return run_service().get_capacity(identity)
    except KeyError as error:
        raise HTTPException(status_code=404, detail=str(error)) from error
    except ValueError as error:
        raise HTTPException(status_code=409, detail=str(error)) from error


@app.put(
    "/api/runs/{identity}/capacity",
    response_model=CapacityPortfolioEstimate,
)
def update_capacity(
    identity: str, update: CapacityUpdate
) -> CapacityPortfolioEstimate:
    try:
        return run_service().update_capacity(identity, update)
    except KeyError as error:
        raise HTTPException(status_code=404, detail=str(error)) from error
    except ValueError as error:
        raise HTTPException(status_code=409, detail=str(error)) from error


@app.get("/api/runs/{identity}/capacity/export")
def export_capacity(
    identity: str, format: Literal["json", "csv"] = "json"
) -> Response:
    try:
        estimate = run_service().get_capacity(identity)
    except KeyError as error:
        raise HTTPException(status_code=404, detail=str(error)) from error
    except ValueError as error:
        raise HTTPException(status_code=409, detail=str(error)) from error
    if format == "csv":
        return Response(
            capacity_csv(estimate),
            media_type="text/csv",
            headers={"Content-Disposition": 'attachment; filename="capacity-estimate.csv"'},
        )
    return Response(
        estimate.model_dump_json(indent=2),
        media_type="application/json",
        headers={"Content-Disposition": 'attachment; filename="capacity-estimate.json"'},
    )


@app.post("/api/runs/{identity}/cancel", response_model=Run)
def cancel_run(identity: str) -> Run:
    get_run(identity)
    return run_service().cancel(identity)


@app.post("/api/runs/{identity}/generate", response_model=list[Candidate])
def generate_run(identity: str, target: Target = "notebook") -> list[Candidate]:
    get_run(identity)
    try:
        return run_service().write_artifacts(identity, target).candidates
    except (OSError, ValueError) as error:
        raise HTTPException(status_code=409, detail=str(error)) from error


@app.post("/api/runs/{identity}/previews", response_model=list[Candidate])
def preview_run(identity: str, target: Target = "notebook") -> list[Candidate]:
    get_run(identity)
    try:
        return run_service().preview_candidates(identity, target)
    except (OSError, ValueError) as error:
        raise HTTPException(status_code=409, detail=str(error)) from error


@app.post("/api/runs/{identity}/publications", response_model=PublicationReference)
def publish_run(identity: str) -> PublicationReference:
    get_run(identity)
    try:
        publication = run_service().publish_artifacts(identity)
        return PublicationReference(run_id=publication.run_id, digest=publication.digest)
    except (OSError, ValueError) as error:
        raise HTTPException(status_code=409, detail=str(error)) from error


@app.get("/api/runs/{identity}/publications/{digest}", response_model=PublicationReference)
def verify_run_publication(identity: str, digest: str) -> PublicationReference:
    get_run(identity)
    try:
        publication = run_service().verify_publication(identity, digest)
        return PublicationReference(run_id=publication.run_id, digest=publication.digest)
    except (OSError, ValueError) as error:
        raise HTTPException(status_code=409, detail=str(error)) from error


@app.get("/api/runs/{identity}/publications/{digest}/download")
def download_run_publication(identity: str, digest: str) -> Response:
    get_run(identity)
    try:
        content = run_service().publication_package(identity, digest)
    except (OSError, ValueError) as error:
        raise HTTPException(status_code=409, detail=str(error)) from error
    return Response(
        content,
        media_type="application/zip",
        headers={"Content-Disposition": f'attachment; filename="publication-{digest}.zip"'},
    )


@app.post(
    "/api/runs/{identity}/targets/{platform_id}/evaluate",
    response_model=list[RunTargetEvaluation],
)
def evaluate_run_target(identity: str, platform_id: str) -> list[RunTargetEvaluation]:
    get_run(identity, include_result=False)
    try:
        return run_service().evaluate_target(identity, platform_id, target_registry())
    except UnknownTargetPlatformError as error:
        raise HTTPException(status_code=404, detail=str(error)) from error
    except (UnsupportedTargetCapabilityError, ValueError) as error:
        raise HTTPException(status_code=409, detail=str(error)) from error


@app.post(
    "/api/runs/{identity}/targets/{platform_id}/generate",
    response_model=list[TargetGenerationResult],
)
def generate_run_target(
    identity: str,
    platform_id: str,
    target_kind: str = Query(min_length=1),
) -> list[TargetGenerationResult]:
    get_run(identity, include_result=False)
    try:
        return run_service().generate_for_target(
            identity, platform_id, target_kind, target_registry()
        )
    except UnknownTargetPlatformError as error:
        raise HTTPException(status_code=404, detail=str(error)) from error
    except (UnsupportedTargetCapabilityError, ValueError) as error:
        raise HTTPException(status_code=409, detail=str(error)) from error


@app.get(
    "/api/runs/{identity}/targets/{platform_id}/capacity",
    response_model=list[TargetCapacityResult],
)
def estimate_run_target_capacity(
    identity: str, platform_id: str
) -> list[TargetCapacityResult]:
    get_run(identity, include_result=False)
    try:
        return run_service().estimate_target_capacity(
            identity, platform_id, target_registry()
        )
    except UnknownTargetPlatformError as error:
        raise HTTPException(status_code=404, detail=str(error)) from error
    except (UnsupportedTargetCapabilityError, ValueError) as error:
        raise HTTPException(status_code=409, detail=str(error)) from error


@app.post(
    "/api/runs/{identity}/neutral-assessment",
    response_model=NeutralEstateAssessmentResponse,
)
def assess_run_neutral(identity: str) -> NeutralEstateAssessmentResponse:
    get_run(identity)
    try:
        return run_service().assess_neutral(identity)
    except (OSError, ValueError) as error:
        raise HTTPException(status_code=409, detail=str(error)) from error


@app.get(
    "/api/runs/{identity}/neutral-assessment",
    response_model=NeutralEstateAssessmentResponse,
)
def get_run_neutral_assessment(identity: str) -> NeutralEstateAssessmentResponse:
    get_run(identity)
    try:
        return run_service().get_neutral_assessment(identity)
    except KeyError as error:
        raise HTTPException(status_code=404, detail=str(error)) from error


@app.get(
    "/api/runs/{identity}/targets/{platform_id}/evaluate",
    response_model=list[RunTargetEvaluation],
)
def get_run_target_evaluation(identity: str, platform_id: str) -> list[RunTargetEvaluation]:
    get_run(identity)
    try:
        return run_service().get_target_evaluations(identity, platform_id)
    except KeyError as error:
        raise HTTPException(status_code=404, detail=str(error)) from error


@app.get("/api/runs/{identity}/export")
def export_run(identity: str, format: Literal["json", "csv"] = "json") -> Response:
    run = get_run(identity)
    if run.result is None:
        raise HTTPException(status_code=409, detail="Run has no assessment results")
    if format == "csv":
        return Response(
            run_service().export_csv(identity),
            media_type="text/csv",
            headers={"Content-Disposition": 'attachment; filename="assessment.csv"'},
        )
    return Response(
        run.result.model_dump_json(indent=2),
        media_type="application/json",
        headers={"Content-Disposition": 'attachment; filename="assessment.json"'},
    )


@app.post("/api/runs/{identity}/dry-run", response_model=DryRunResult)
def deployment_preview(identity: str, selection: DevSelection) -> DryRunResult:
    return dry_run(
        preview_run(identity, selection.target),
        approved_workspace=os.getenv("ACCELERATOR_DEV_WORKSPACE"),
        requested_workspace=selection.workspace,
    )


@app.post(
    "/api/runs/{identity}/deploy/github",
    response_model=GitHubDeploymentResult,
    status_code=202,
)
def deploy_with_github(
    identity: str, selection: GitHubDeploymentSelection
) -> GitHubDeploymentResult:
    selected_target, artifact_path, publication = _plan_deployment_dispatch(
        identity,
        selection.source_workflow,
        selection.target,
        isolate_local_artifacts=selection.isolate_local_artifacts,
        publication_digest=selection.publication_digest,
    )
    effective_selection = selection.model_copy(update={"target": selected_target})
    try:
        service = GitHubDeploymentService.from_environment()
        return service.deploy(
            selection=effective_selection,
            workspace_id=(
                os.getenv("FABRIC_WORKSPACE_ID")
                or os.getenv("ACCELERATOR_DEV_WORKSPACE", "")
                or ""
            ).strip(),
            artifact_path=artifact_path,
            publication=publication,
        )
    except GitHubConfigurationError as error:
        raise HTTPException(status_code=503, detail=str(error)) from error
    except GitHubDeploymentError as error:
        raise HTTPException(status_code=502, detail=str(error)) from error


@app.post(
    "/api/runs/{identity}/deploy/gitlab",
    response_model=GitLabDeploymentResult,
    status_code=202,
)
def deploy_with_gitlab(
    identity: str,
    selection: GitLabDeploymentSelection,
) -> GitLabDeploymentResult:
    selected_target, artifact_path, publication = _plan_deployment_dispatch(
        identity,
        selection.source_workflow,
        selection.target,
        isolate_local_artifacts=selection.isolate_local_artifacts,
        publication_digest=selection.publication_digest,
    )
    effective_selection = selection.model_copy(update={"target": selected_target})
    try:
        service = GitLabDeploymentService.from_environment()
        return service.deploy(
            selection=effective_selection,
            workspace_id=(
                os.getenv("FABRIC_WORKSPACE_ID")
                or os.getenv("ACCELERATOR_DEV_WORKSPACE", "")
                or ""
            ).strip(),
            artifact_path=artifact_path,
            publication=publication,
        )
    except GitLabConfigurationError as error:
        raise HTTPException(status_code=503, detail=str(error)) from error
    except GitLabDeploymentError as error:
        raise HTTPException(status_code=502, detail=str(error)) from error


def _plan_deployment_dispatch(
    identity: str,
    source_workflow: str,
    requested_target: DeploymentTarget,
    *,
    isolate_local_artifacts: bool,
    publication_digest: str | None,
) -> tuple[DeploymentTarget, str, PublicationDispatch | None]:
    return plan_deployment_dispatch(
        run_service(),
        identity,
        source_workflow,
        requested_target,
        isolate_local_artifacts=isolate_local_artifacts,
        publication_digest=publication_digest,
    )


def _resolve_deployment_artifact(
    identity: str,
    source_workflow: str,
    requested_target: DeploymentTarget,
    *,
    isolate_local_artifacts: bool = False,
) -> tuple[Candidate, DeploymentTarget, str]:
    return resolve_deployment_artifact(
        run_service(),
        identity,
        source_workflow,
        requested_target,
        isolate_local_artifacts=isolate_local_artifacts,
    )


@app.get("/api/runs/{identity}/candidates")
def download_candidates(identity: str, target: Target = "notebook") -> Response:
    get_run(identity)
    try:
        content = run_service().candidate_package(identity, target)
    except (OSError, ValueError) as error:
        raise HTTPException(status_code=409, detail=str(error)) from error
    return Response(
        content,
        media_type="application/zip",
        headers={"Content-Disposition": f'attachment; filename="{target}-previews.zip"'},
    )


@app.get("/api/runs/{identity}/bundle")
def download_workflow_bundle(
    identity: str,
    workflow: Annotated[str, Query(min_length=1, max_length=4096)],
) -> Response:
    get_run(identity)
    try:
        content, filename = run_service().workflow_package(identity, workflow)
    except (OSError, ValueError) as error:
        raise HTTPException(status_code=409, detail=str(error)) from error
    return Response(
        content,
        media_type="application/zip",
        headers={"Content-Disposition": f'attachment; filename="{filename}"'},
    )


@app.get("/api/runs/{identity}/evidence", response_model=EvidenceResponse)
def inspect_evidence(
    identity: str,
    response: Response,
    workflow_index: int | None = None,
) -> EvidenceResponse:
    response.headers["Cache-Control"] = "no-store"
    get_run(identity)
    try:
        return run_service().evidence(identity, workflow_index)
    except KeyError as error:
        raise HTTPException(status_code=404, detail=str(error)) from error
    except (OSError, ValueError) as error:
        raise HTTPException(status_code=409, detail=str(error)) from error


def resolve_web_root() -> Path:
    """Resolve compiled analyst UI assets for editable, wheel, or frozen installs."""
    configured = os.getenv("ACCELERATOR_WEB_ROOT", "").strip()
    if configured:
        return Path(configured)

    packaged = Path(__file__).resolve().parents[1] / "web_dist"
    if (packaged / "index.html").is_file():
        return packaged

    editable = Path(__file__).resolve().parents[3] / "apps" / "web" / "dist"
    if (editable / "index.html").is_file():
        return editable

    cwd_dist = Path.cwd() / "apps" / "web" / "dist"
    if (cwd_dist / "index.html").is_file():
        return cwd_dist

    if (Path(__file__).resolve().parents[3] / "apps" / "web").is_dir():
        return editable
    return cwd_dist


WEB_ROOT = resolve_web_root()
if (WEB_ROOT / "assets").is_dir():
    app.mount("/assets", StaticFiles(directory=WEB_ROOT / "assets"), name="assets")


@app.get("/", response_class=HTMLResponse)
def analyst_app() -> HTMLResponse:
    index = WEB_ROOT / "index.html"
    if not index.is_file():
        return HTMLResponse(
            "<h1>Build the analyst UI first</h1><p>Run npm run build in apps\\web.</p>",
            status_code=503,
            headers={"Cache-Control": "no-store"},
        )
    return HTMLResponse(
        index.read_text(encoding="utf-8"),
        headers={"Cache-Control": "no-store"},
    )
