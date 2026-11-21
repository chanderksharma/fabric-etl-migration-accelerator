"""FastAPI entry point."""

import asyncio
import os
import secrets
import shutil
import tempfile
from collections.abc import AsyncIterator, Awaitable, Callable
from concurrent.futures import Future, ThreadPoolExecutor
from contextlib import asynccontextmanager, suppress
from pathlib import Path, PurePosixPath
from typing import Annotated, Literal

from dotenv import load_dotenv
from fastapi import FastAPI, File, Form, HTTPException, Query, Request, UploadFile
from fastapi.responses import HTMLResponse, RedirectResponse, Response
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, Field, TypeAdapter
from starlette.concurrency import run_in_threadpool
from starlette.middleware.trustedhost import TrustedHostMiddleware

from accelerator import __version__
from accelerator.application import AssessmentApplication
from accelerator.assessment import REGISTRY_VERSION, RULES_VERSION, registry_entries
from accelerator.capacity import CapacityPortfolioEstimate, CapacityUpdate, capacity_csv
from accelerator.deployment import DryRunResult, dry_run
from accelerator.discovery import InputRejectedError, validate_member_path
from accelerator.evidence import EvidenceResponse
from accelerator.generation import Candidate, Target
from accelerator.github_deployment import (
    GitHubConfigurationError,
    GitHubDeploymentError,
    GitHubDeploymentResult,
    GitHubDeploymentSelection,
    GitHubDeploymentService,
)
from accelerator.gitlab_deployment import (
    GitLabConfigurationError,
    GitLabDeploymentError,
    GitLabDeploymentResult,
    GitLabDeploymentSelection,
    GitLabDeploymentService,
)
from accelerator.graph import WorkflowGraph
from accelerator.runs import Run, RunService, SnapshotPreview
from accelerator.schemas import DiscoverySummaryResponse, EstateAssessmentResponse
from accelerator.spi import TargetPlatformInfo
from accelerator.targets import (
    TargetPlatformRegistry,
    UnknownTargetPlatformError,
    create_default_target_registry,
)

load_dotenv()


@asynccontextmanager
async def lifespan(api: FastAPI) -> AsyncIterator[None]:
    if not hasattr(api.state, "run_service") or api.state.run_service.closed:
        api.state.run_service = _new_run_service()
    executor = ThreadPoolExecutor(max_workers=2, thread_name_prefix="accelerator")
    futures: dict[str, Future[None]] = {}

    async def resume_pending() -> None:
        while True:
            for identity in await run_in_threadpool(api.state.run_service.pending):
                if identity not in futures and len(futures) < 2:
                    futures[identity] = executor.submit(api.state.run_service.execute, identity)
            for identity, future in list(futures.items()):
                if future.done():
                    future.result()
                    del futures[identity]
            await asyncio.sleep(0.2)

    worker = asyncio.create_task(resume_pending())
    try:
        yield
    finally:
        worker.cancel()
        with suppress(asyncio.CancelledError):
            await worker
        await run_in_threadpool(executor.shutdown, wait=True)
        api.state.run_service.close()


app = FastAPI(title="Alteryx to Fabric Accelerator", version=__version__, lifespan=lifespan)
app.add_middleware(TrustedHostMiddleware, allowed_hosts=["127.0.0.1", "localhost"])
app.state.csrf_token = secrets.token_urlsafe(32)
application = AssessmentApplication()
MAX_BROWSER_UPLOAD_BYTES = 100 * 1024 * 1024
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
        staged = await _stage_uploads(files, sandbox)
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
        staged = await _stage_uploads(files, sandbox)
        return await run_in_threadpool(application.assess, staged[0] if mode == "zip" else sandbox)
    except InputRejectedError as error:
        raise HTTPException(status_code=400, detail=error.detail) from error
    finally:
        shutil.rmtree(sandbox, ignore_errors=False)


async def _stage_uploads(files: list[UploadFile], sandbox: Path) -> list[Path]:
    staged: list[Path] = []
    total_size = 0
    seen_names: set[str] = set()
    for upload in files:
        relative_path = _safe_upload_path(upload.filename)
        key = str(relative_path).casefold()
        if key in seen_names:
            raise HTTPException(status_code=400, detail="Uploaded names collide")
        seen_names.add(key)
        destination = sandbox.joinpath(*relative_path.parts)
        destination.parent.mkdir(parents=True, exist_ok=True)
        size = 0
        with destination.open("wb") as target:
            while chunk := await upload.read(1024 * 1024):
                size += len(chunk)
                total_size += len(chunk)
                if size > MAX_BROWSER_UPLOAD_BYTES or total_size > MAX_BROWSER_UPLOAD_BYTES:
                    raise HTTPException(
                        status_code=413,
                        detail=f"{upload.filename} exceeds the browser upload limit",
                    )
                target.write(chunk)
        staged.append(destination)
    return staged


def _safe_upload_path(filename: str | None) -> PurePosixPath:
    if not filename:
        raise HTTPException(status_code=400, detail="An uploaded file has no name")
    try:
        return validate_member_path(Path("upload"), filename)
    except InputRejectedError as error:
        raise HTTPException(status_code=400, detail=error.detail) from error


class LocalSelection(BaseModel):
    path: str = Field(min_length=1)


class FolderSelectionResponse(BaseModel):
    path: str | None = None


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


class Confirmation(BaseModel):
    snapshot_id: str = Field(pattern=r"^[a-f0-9]{64}$")


class DevSelection(BaseModel):
    workspace: str = Field(min_length=1)
    target: Target = "notebook"


def run_service() -> RunService:
    if not hasattr(app.state, "run_service") or app.state.run_service.closed:
        app.state.run_service = _new_run_service()
    service: RunService = app.state.run_service
    return service


def _new_run_service() -> RunService:
    return RunService(
        Path(os.getenv("ACCELERATOR_STATE_DIR", ".accelerator")),
        artifact_root=Path(
            os.getenv("ACCELERATOR_ARTIFACT_DIR", "generated-fabric-workflows")
        ),
    )


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
        app.state.target_registry = create_default_target_registry()
    registry: TargetPlatformRegistry = app.state.target_registry
    return registry


@app.get("/api/targets")
def list_target_platforms() -> dict[str, object]:
    return {
        "targets": [
            info.model_dump(mode="json")
            for info in target_registry().list_providers()
        ]
    }


@app.get("/api/targets/{platform_id}", response_model=TargetPlatformInfo)
def get_target_platform(platform_id: str) -> TargetPlatformInfo:
    try:
        return target_registry().get(platform_id).info()
    except UnknownTargetPlatformError as error:
        raise HTTPException(status_code=404, detail=str(error)) from error


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
        staged = await _stage_uploads(files, Path(directory))
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
def get_run(identity: str) -> Run:
    try:
        return run_service().get_run(identity)
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
        generate_run(identity, selection.target),
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
    _, selected_target, artifact_path = _resolve_deployment_artifact(
        identity,
        selection.source_workflow,
        selection.target,
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
    _, selected_target, artifact_path = _resolve_deployment_artifact(
        identity,
        selection.source_workflow,
        selection.target,
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
        )
    except GitLabConfigurationError as error:
        raise HTTPException(status_code=503, detail=str(error)) from error
    except GitLabDeploymentError as error:
        raise HTTPException(status_code=502, detail=str(error)) from error


def _resolve_deployment_artifact(
    identity: str,
    source_workflow: str,
    requested_target: Literal["notebook", "dataflow", "pipeline", "bundle"],
) -> tuple[
    Candidate,
    Literal["notebook", "dataflow", "pipeline", "bundle"],
    str,
]:
    get_run(identity)
    candidate: Candidate | None = None
    selected_target: Literal["notebook", "dataflow", "pipeline", "bundle"] | None = None
    diagnostics: list[str] = []
    targets: tuple[Target, ...] = ("dataflow", "notebook", "pipeline")
    candidates_by_target: dict[Target, Candidate] = {}
    for target in targets:
        try:
            written = run_service().write_artifacts(identity, target)
        except (OSError, ValueError) as error:
            raise HTTPException(status_code=409, detail=str(error)) from error
        current = next(
            (
                item
                for item in written.candidates
                if item.workflow == source_workflow
                and item.target == target
            ),
            None,
        )
        if current is None:
            continue
        candidates_by_target[target] = current
        diagnostics.extend(f"{target}: {message}" for message in current.diagnostics[:3])
        if requested_target == "bundle":
            continue
        if requested_target != target:
            continue
        if current.deployable and current.artifact_path:
            candidate = current
            selected_target = target
            break
    if requested_target == "bundle":
        deployable = [
            item
            for item in candidates_by_target.values()
            if item.deployable and item.artifact_path
        ]
        artifact_paths = {item.artifact_path for item in deployable}
        if len(artifact_paths) == 1:
            artifact_path = next(iter(artifact_paths))
            assert artifact_path is not None
            folder = run_service().artifact_root / Path(*artifact_path.split("/"))
            if (folder / "deployment-bundle.json").is_file():
                candidate = deployable[0]
                selected_target = "bundle"
    if candidate is None or selected_target is None:
        raise HTTPException(
            status_code=409,
            detail=(
                "No requested native Fabric implementation is available."
                + (f" Diagnostics: {'; '.join(diagnostics)}." if diagnostics else "")
            ),
        )
    artifact_path = candidate.artifact_path
    if artifact_path is None:
        raise HTTPException(status_code=409, detail="Selected native artifact has no path")
    if selected_target not in {"notebook", "dataflow", "pipeline", "bundle"}:
        raise HTTPException(status_code=500, detail="Resolved deployment target is invalid")
    return candidate, selected_target, artifact_path


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


WEB_ROOT = Path(
    os.getenv(
        "ACCELERATOR_WEB_ROOT",
        str(Path(__file__).resolve().parents[2] / "apps" / "web" / "dist"),
    )
)
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
