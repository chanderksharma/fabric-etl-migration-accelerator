"""Portfolio assessment, Fabric fit, and generation are separate stages."""

from __future__ import annotations

import ast
import shutil
import sqlite3
import sys
import time
from collections.abc import Iterable, Iterator
from contextlib import closing
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from accelerator.runtime import identity
from accelerator.runtime.runs import RunService
from accelerator.server.api import app
from etl_migration_core.targets.registry import TargetPlatformRegistry
from etl_target_fabric import application, evaluation
from etl_target_fabric.application import FabricAssessmentApplication
from etl_target_fabric.assessment import evaluator, portfolio
from etl_target_fabric.assessment.schemas import WorkflowAssessmentResponse
from etl_target_fabric.compilers import alteryx as alteryx_compiler
from etl_target_fabric.compilers import ir as ir_compiler
from etl_target_fabric.provider import FabricTargetProvider

REPO = Path(__file__).parents[1]
ALTERYX = REPO / "alteryx-workflows"
POWERCENTER = REPO / "tests" / "fixtures" / "powercenter"
SOURCES = pytest.mark.parametrize("source", [ALTERYX, POWERCENTER], ids=["alteryx", "powercenter"])
ROUTING_FIELDS = (
    "recommended_target",
    "target_components",
    "migration_wave",
    "estimated_effort_days",
    "recommendation_reason",
)


def _fabric_only_registry() -> TargetPlatformRegistry:
    return TargetPlatformRegistry((FabricTargetProvider(),))


def _routing(assessments: Iterable[WorkflowAssessmentResponse]) -> dict[str, tuple[object, ...]]:
    return {
        item.path: tuple(getattr(item, field) for field in ROUTING_FIELDS) for item in assessments
    }


def _completed_run(service: RunService, source: Path) -> str:
    run = service.create_run(service.preview(source).snapshot_id)
    service.execute(run.id)
    return run.id


def _forbid_compilers(monkeypatch: pytest.MonkeyPatch) -> list[str]:
    """Make every binding of a compiler entry point fail, wherever it was imported."""
    entry_points = {
        id(alteryx_compiler.generate_candidate): "generate_candidate",
        id(ir_compiler.compile_asset): "compile_asset",
        id(ir_compiler.compile_asset_targets): "compile_asset_targets",
    }
    calls: list[str] = []

    def forbidden(name: str) -> object:
        def fail(*_args: object, **_kwargs: object) -> object:
            calls.append(name)
            raise AssertionError(f"{name} ran during portfolio assessment")

        return fail

    for module in list(sys.modules.values()):
        namespace = getattr(module, "__dict__", None)
        if not isinstance(namespace, dict):
            continue
        for attribute, value in list(namespace.items()):
            name = entry_points.get(id(value))
            if name is not None:
                monkeypatch.setattr(module, attribute, forbidden(name))
    return calls


@SOURCES
def test_portfolio_assessment_never_runs_a_compiler(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, source: Path
) -> None:
    calls = _forbid_compilers(monkeypatch)

    FabricAssessmentApplication().assess(source)
    with RunService(tmp_path / "state") as service:
        run_id = _completed_run(service, source)
        run = service.get_run(run_id)
        baseline = service.get_neutral_assessment(run_id)

    assert run.status == "completed"
    assert run.result is not None
    assert run.result.workflow_count > 0
    assert run.result.failed_count == 0
    assert run.routing_basis == "static_mapping"
    assert baseline.workflow_count == run.result.workflow_count
    assert calls == []


@SOURCES
def test_confirmed_fit_reproduces_the_compiler_routing_it_replaced(
    tmp_path: Path, source: Path
) -> None:
    routed = FabricAssessmentApplication().assess(source, route_native=True)
    static_facade = FabricAssessmentApplication().assess(source)

    with RunService(tmp_path / "state") as service:
        run_id = _completed_run(service, source)
        static = service.get_run(run_id)
        service.evaluate_target(run_id, "fabric", _fabric_only_registry())
        confirmed = service.get_run(run_id)

    assert static.result is not None
    assert confirmed.result is not None
    assert static.routing_basis == "static_mapping"
    assert confirmed.routing_basis == "compiler_confirmed"
    assert _routing(static.result.assessments) == _routing(static_facade.assessments)
    assert _routing(confirmed.result.assessments) == _routing(routed.assessments)
    assert [item.path for item in confirmed.result.assessments] == [
        item.path for item in static.result.assessments
    ]


def test_the_stages_disagree_where_the_compiler_changes_the_route(tmp_path: Path) -> None:
    # Guards the equivalence test above against passing because nothing ever changes.
    with RunService(tmp_path / "state") as service:
        run_id = _completed_run(service, ALTERYX)
        static = service.get_run(run_id).result
        confirmed = service.ensure_fabric_fit(run_id).result

    assert static is not None
    assert confirmed is not None
    before = {item.path: item for item in static.assessments}
    after = {item.path: item for item in confirmed.assessments}
    sample = "sample_alteryx_workflow.yxmd"
    assert before[sample].recommended_target == "Dataflow Gen2"
    assert after[sample].recommended_target == "Manual rework"
    assert after[sample].migration_wave == "Redesign"
    assert sum(before[path] != after[path] for path in before) >= 5


def test_evaluation_is_idempotent_and_reads_only_the_static_assessment(tmp_path: Path) -> None:
    registry = _fabric_only_registry()
    with RunService(tmp_path / "state") as service:
        run_id = _completed_run(service, ALTERYX)
        first = service.evaluate_target(run_id, "fabric", registry)
        confirmed = service.get_run(run_id).result
        second = service.evaluate_target(run_id, "fabric", registry)
        again = service.get_run(run_id).result

    assert first == second
    assert confirmed == again


def test_assessment_packages_do_not_depend_on_code_generation() -> None:
    packages = REPO / "packages"
    fabric = packages / "etl-target-fabric" / "src" / "etl_target_fabric"
    forbidden = (
        "etl_target_fabric.compilers",
        "etl_target_fabric.evaluation",
        "etl_target_fabric.application",
        "etl_target_fabric.provider",
        "etl_target_fabric.delivery",
    )
    offenders = _forbidden_imports(sorted((fabric / "assessment").glob("*.py")), forbidden)
    assert offenders == [], "portfolio assessment must not import code generation"

    neutral = sorted((packages / "etl-portfolio-assessment" / "src").rglob("*.py"))
    assert _forbidden_imports(neutral, ("etl_target_",)) == []

    core = sorted((packages / "etl-migration-core" / "src").rglob("*.py"))
    assert _forbidden_imports(core, ("etl_target_", "etl_portfolio_assessment")) == []

    # Layering inside the Fabric package: compilers sit below evaluation and the facade.
    compilers = sorted((fabric / "compilers").rglob("*.py"))
    above = ("etl_target_fabric.evaluation", "etl_target_fabric.application")
    assert _forbidden_imports(compilers, above) == []


def _forbidden_imports(files: Iterable[Path], prefixes: tuple[str, ...]) -> list[str]:
    """List imports of ``prefixes``, allowing lazy forwarding inside a module ``__getattr__``."""
    offenders: list[str] = []
    for path in files:
        for module, lazily_forwarded in _imports(ast.parse(path.read_text(encoding="utf-8"))):
            if lazily_forwarded:
                continue
            if any(module == prefix or module.startswith(prefix + ".") for prefix in prefixes):
                offenders.append(f"{path.name}: {module}")
    return offenders


def _imports(tree: ast.AST, in_getattr: bool = False) -> list[tuple[str, bool]]:
    found: list[tuple[str, bool]] = []
    for node in ast.iter_child_nodes(tree):
        inside = in_getattr or (isinstance(node, ast.FunctionDef) and node.name == "__getattr__")
        if isinstance(node, ast.Import):
            found.extend((alias.name, inside) for alias in node.names)
        elif isinstance(node, ast.ImportFrom) and node.module:
            found.append((node.module, inside))
        found.extend(_imports(node, inside))
    return found


def test_deprecated_import_paths_resolve_to_the_relocated_code() -> None:
    assert evaluator.apply_native_route is evaluation.apply_native_route
    assert evaluator.apply_alteryx_native_route is evaluation.apply_alteryx_native_route
    assert evaluator.evaluate_etl_native_route is evaluation.evaluate_etl_native_route
    assert portfolio.FabricAssessmentApplication is application.FabricAssessmentApplication
    with pytest.raises(AttributeError):
        evaluator.__getattr__("no_such_name")
    with pytest.raises(AttributeError):
        portfolio.__getattr__("no_such_name")


def test_cache_keys_depend_on_the_compilers_only_where_a_compiler_runs(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    with RunService(tmp_path / "state") as service:
        item = service.preview(ALTERYX).workflows[0]
        registry = service.source_registry

    def keys() -> tuple[str, str, str]:
        return (
            identity.assessment_cache_key(registry, item),
            identity.candidate_cache_key(
                source_sha256=item.sha256,
                display_path=item.display_path,
                platform=str(item.source_platform),
                target="notebook",
                asset_id=item.display_path,
            ),
            identity.fabric_fit_key(FabricTargetProvider.provider_version),
        )

    assessment, candidate, fit = keys()
    monkeypatch.setattr(identity, "COMPILER_VERSION", "9.9.9")
    changed_assessment, changed_candidate, changed_fit = keys()

    assert changed_assessment == assessment, "a compiler change must not invalidate assessment"
    assert changed_candidate != candidate
    assert changed_fit != fit


def test_a_fit_computed_with_other_versions_is_ignored_then_recomputed(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    with RunService(tmp_path / "state") as service:
        run_id = _completed_run(service, ALTERYX)
        static = service.get_run(run_id).result
        assert static is not None
        assert service.ensure_fabric_fit(run_id).routing_basis == "compiler_confirmed"

        monkeypatch.setattr(identity, "COMPILER_VERSION", "9.9.9")
        stale = service.get_run(run_id)
        assert stale.routing_basis == "static_mapping"
        assert stale.result is not None
        assert _routing(stale.result.assessments) == _routing(static.assessments)

        assert service.ensure_fabric_fit(run_id).routing_basis == "compiler_confirmed"


def test_generation_confirms_the_fit_it_consumes_and_candidates_do_not(tmp_path: Path) -> None:
    with RunService(tmp_path / "state", artifact_root=tmp_path / "artifacts") as service:
        run_id = _completed_run(service, ALTERYX)

        service.generate(run_id, "notebook")
        assert service.get_run(run_id).routing_basis == "static_mapping"

        service.write_all_artifacts(run_id)
        assert service.get_run(run_id).routing_basis == "compiler_confirmed"


def test_a_run_stored_before_the_basis_was_recorded_is_left_as_stored(tmp_path: Path) -> None:
    with RunService(tmp_path / "state") as service:
        run_id = _completed_run(service, ALTERYX)
        stored = service.get_run(run_id).result
        with closing(sqlite3.connect(service.database)) as connection, connection:
            connection.execute("UPDATE runs SET assessment_basis=NULL WHERE id=?", (run_id,))

        legacy = service.get_run(run_id)
        service.ensure_fabric_fit(run_id)

        assert legacy.routing_basis == "compiler_confirmed"
        assert legacy.result == stored
        with pytest.raises(KeyError):
            service.get_target_evaluations(run_id, "fabric")


def test_a_workflow_that_failed_assessment_does_not_block_the_fit(tmp_path: Path) -> None:
    source = tmp_path / "estate"
    source.mkdir()
    shutil.copyfile(ALTERYX / "sample_alteryx_workflow.yxmd", source / "good.yxmd")
    (source / "bad.yxmd").write_bytes(b"<AlteryxDocument><Nodes><Node ToolID='1'>")

    with RunService(tmp_path / "state") as service:
        run_id = _completed_run(service, source)
        run = service.get_run(run_id)
        evaluations = service.evaluate_target(run_id, "fabric", _fabric_only_registry())
        confirmed = service.get_run(run_id)

    assert run.result is not None
    assert run.result.failed_count == 1
    assert [item.source_path for item in evaluations] == ["good.yxmd"]
    assert confirmed.routing_basis == "compiler_confirmed"


@pytest.fixture
def api_client(tmp_path: Path) -> Iterator[TestClient]:
    previous = getattr(app.state, "run_service", None)
    app.state.run_service = RunService(tmp_path / "api-state", artifact_root=tmp_path / "artifacts")
    try:
        with TestClient(app, base_url="http://localhost") as client:
            yield client
    finally:
        if previous is None:
            del app.state.run_service
        else:
            app.state.run_service = previous


def _api_run(client: TestClient, source: Path) -> str:
    snapshot = client.post("/api/snapshots/local", json={"path": str(source)}).json()
    created = client.post("/api/runs", json={"snapshot_id": snapshot["snapshot_id"]})
    run_id: str = created.json()["id"]
    for _ in range(200):
        if client.get(f"/api/runs/{run_id}/status").json()["status"] == "completed":
            return run_id
        time.sleep(0.03)
    pytest.fail("the local worker did not complete the run")


def _basis(client: TestClient, run_id: str) -> str:
    basis: str = client.get(f"/api/runs/{run_id}").json()["routing_basis"]
    return basis


def test_exports_say_whether_the_fabric_routing_was_confirmed(api_client: TestClient) -> None:
    run_id = _api_run(api_client, ALTERYX)

    for export in ("json", "csv"):
        static = api_client.get(f"/api/runs/{run_id}/export", params={"format": export})
        assert static.status_code == 200
        assert static.headers["x-routing-basis"] == "static_mapping"
    static_csv = api_client.get(f"/api/runs/{run_id}/export", params={"format": "csv"}).text

    assert api_client.post(f"/api/runs/{run_id}/targets/fabric/evaluate").status_code == 200

    for export in ("json", "csv"):
        confirmed = api_client.get(f"/api/runs/{run_id}/export", params={"format": export})
        assert confirmed.headers["x-routing-basis"] == "compiler_confirmed"
    assert api_client.get(f"/api/runs/{run_id}/export", params={"format": "csv"}).text != static_csv


def test_the_status_route_stays_light_and_the_run_route_carries_the_basis(
    api_client: TestClient,
) -> None:
    run_id = _api_run(api_client, ALTERYX)

    status = api_client.get(f"/api/runs/{run_id}/status").json()
    run = api_client.get(f"/api/runs/{run_id}").json()

    assert "result" not in status
    assert "routing_basis" not in status
    assert run["routing_basis"] == "static_mapping"


def test_only_routes_that_consume_the_fit_confirm_it(api_client: TestClient) -> None:
    run_id = _api_run(api_client, ALTERYX)
    assert _basis(api_client, run_id) == "static_mapping"

    # Pure candidate compilation does not read the assessment, so it must not confirm it.
    candidates = api_client.get(
        f"/api/runs/{run_id}/workflows/0/candidates", params={"target": "notebook"}
    )
    assert candidates.status_code == 200
    job = api_client.post(f"/api/runs/{run_id}/jobs", params={"target": "notebook"})
    assert job.status_code == 202
    for _ in range(300):
        jobs = api_client.get(f"/api/runs/{run_id}/jobs").json()
        if jobs[0]["status"] in {"completed", "failed"}:
            break
        time.sleep(0.03)
    assert jobs[0]["status"] == "completed"
    assert _basis(api_client, run_id) == "static_mapping"

    # Anything that builds an artifact tree takes its bundle from the confirmed target
    # components, so a preview confirms first, as do generate, packages, and publication.
    previews = api_client.post(f"/api/runs/{run_id}/previews", params={"target": "notebook"})
    assert previews.status_code == 200
    assert _basis(api_client, run_id) == "compiler_confirmed"
