"""Fault isolation, schema migration, retention, and plugin-load contracts."""

from __future__ import annotations

import logging
import sqlite3
import time
from collections.abc import Callable
from contextlib import closing
from dataclasses import dataclass
from pathlib import Path
from typing import Any, cast

import pytest
from fastapi.testclient import TestClient
from typer.testing import CliRunner

from accelerator.cli.app import app as cli_app
from accelerator.runtime.runs import MAX_RUN_ATTEMPTS, RunService
from accelerator.runtime.store import LATEST_SCHEMA_VERSION, RunStore
from accelerator.server.api import app
from accelerator.settings import Settings, configure_logging
from accelerator.targets import create_default_target_registry
from etl_migration_core.contracts.ir import (
    EXTENSIBLE_SOURCE_IR_VERSION,
    AssetType,
    EtlAsset,
    EtlPackage,
)
from etl_migration_core.host import PluginHost
from etl_migration_core.intake.discovery import DiscoveryService
from etl_migration_core.intake.domain import SkipReason
from etl_migration_core.plugins import PLUGIN_ALLOWLIST_ENV, plugin_allowlist_from_environment
from etl_migration_core.sources.base import SourceMatch
from etl_migration_core.sources.defaults import create_default_registry
from etl_migration_core.sources.registry import SourceAdapterFaultError, SourceAdapterRegistry
from etl_migration_core.targets import TargetPlatformRegistry, create_target_registry
from etl_portfolio_assessment.service.application import PortfolioAssessmentApplication
from etl_target_fabric.application import FabricAssessmentApplication

SAMPLE = Path(__file__).parents[1] / "alteryx-workflows" / "sample_alteryx_workflow.yxmd"
DAY = 24 * 60 * 60

# Schema 4 exactly as the last released version created it. Never edit it: a database in
# the field has these tables and nothing else, so changes belong in a new migration step.
SHIPPED_SCHEMA_4 = """
CREATE TABLE snapshots (id TEXT PRIMARY KEY, preview TEXT NOT NULL);
CREATE TABLE runs (
    id TEXT PRIMARY KEY, snapshot TEXT NOT NULL, status TEXT NOT NULL,
    epoch INTEGER NOT NULL DEFAULT 0, lease REAL NOT NULL DEFAULT 0,
    processed INTEGER NOT NULL DEFAULT 0, total INTEGER NOT NULL,
    cache_hits INTEGER NOT NULL DEFAULT 0, error TEXT, result TEXT
);
CREATE TABLE cache (key TEXT PRIMARY KEY, result TEXT NOT NULL);
CREATE TABLE capacity_inputs (
    run_id TEXT NOT NULL,
    workflow_path TEXT NOT NULL,
    input_json TEXT NOT NULL,
    PRIMARY KEY (run_id, workflow_path)
);
CREATE TABLE capacity_settings (
    run_id TEXT PRIMARY KEY,
    settings_json TEXT NOT NULL
);
CREATE TABLE target_evaluations (
    run_id TEXT NOT NULL,
    platform_id TEXT NOT NULL,
    provider_version TEXT NOT NULL,
    evaluations_json TEXT NOT NULL,
    PRIMARY KEY (run_id, platform_id)
);
CREATE TABLE neutral_assessments (
    run_id TEXT PRIMARY KEY,
    assessment_json TEXT NOT NULL
);
PRAGMA user_version=4;
"""


@dataclass(frozen=True)
class FlakyAdapter:
    """Synthetic plugin that can fail while probing or parsing selected files."""

    adapter_id: str = "flaky"
    platform: str = "flaky"
    product: str = "Flaky"
    adapter_version: str = "1.0"
    parser_version: str = "1.0"
    registry_version: str = "1.0"
    rules_version: str = "1.0"
    supported_extensions: tuple[str, ...] = (".flk",)

    def probe(self, path: Path, display_path: str) -> SourceMatch | None:
        content = path.read_bytes()
        if b"probe-boom" in content:
            raise RuntimeError("probe exploded")
        if not content.startswith(b"flaky"):
            return None
        return SourceMatch(
            adapter_id=self.adapter_id,
            platform=self.platform,
            product=self.product,
            asset_type="workflow",
            confidence=100,
            display_path=display_path,
        )

    def parse(self, path: Path, match: SourceMatch) -> EtlPackage:
        if b"parse-boom" in path.read_bytes():
            raise RuntimeError("parse exploded")
        name = Path(match.display_path).stem
        return EtlPackage(
            ir_version=EXTENSIBLE_SOURCE_IR_VERSION,
            source_platform=self.platform,
            source_product=self.product,
            export_id=match.display_path,
            assets=(EtlAsset(native_id=name, name=name, asset_type=AssetType.WORKFLOW),),
        )


class FakeEntryPoint:
    def __init__(self, name: str, loaded: object) -> None:
        self.name = name
        self._loaded = loaded

    def load(self) -> object:
        if isinstance(self._loaded, Exception):
            raise self._loaded
        return self._loaded


def _flaky_folder(tmp_path: Path, **files: bytes) -> Path:
    folder = tmp_path / "input"
    folder.mkdir()
    for name, content in files.items():
        (folder / f"{name}.flk").write_bytes(content)
    return folder


def test_probe_fault_skips_one_file_without_crashing_discovery(tmp_path: Path) -> None:
    folder = _flaky_folder(tmp_path, good=b"flaky good", bad=b"flaky probe-boom")

    summary = DiscoveryService(source_registry=SourceAdapterRegistry((FlakyAdapter(),))).discover(
        folder
    )

    assert [item.display_path for item in summary.workflows] == ["good.flk"]
    skipped = {item.path: item for item in summary.skipped}
    assert skipped["bad.flk"].reason == SkipReason.UNSUPPORTED_INPUT
    assert "Source adapter 'flaky' faulted during probe" in skipped["bad.flk"].detail
    assert "RuntimeError: probe exploded" in skipped["bad.flk"].detail


def test_registry_reports_adapter_faults_as_value_errors(tmp_path: Path) -> None:
    source = tmp_path / "bad.flk"
    source.write_bytes(b"flaky parse-boom")
    registry = SourceAdapterRegistry((FlakyAdapter(),))

    detected = registry.detect(source, source.name)
    with pytest.raises(SourceAdapterFaultError, match="faulted during parse") as raised:
        registry.parse(source, detected.match)
    assert raised.value.adapter_id == "flaky"
    assert raised.value.stage == "parse"


def test_plugin_parse_fault_fails_one_workflow_and_the_run_completes(tmp_path: Path) -> None:
    folder = _flaky_folder(tmp_path, good=b"flaky good", bad=b"flaky parse-boom")

    registry = SourceAdapterRegistry((FlakyAdapter(),))
    with RunService(tmp_path / "state", source_registry=registry) as service:
        run = service.create_run(service.preview(folder).snapshot_id)
        service.execute(run.id)

        finished = service.get_run(run.id)
        assert finished.status == "completed"
        assert finished.error is None
        neutral = service.get_neutral_assessment(run.id)
        assert [item.name for item in neutral.assessments] == ["good"]
        assert len(neutral.failures) == 1
        assert neutral.failures[0].startswith("bad.flk: Source adapter 'flaky' faulted")
        assert "parse exploded" in neutral.failures[0]


def test_unexpected_assessment_fault_fails_one_workflow_not_the_run(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    def explode(*_args: object, **_kwargs: object) -> object:
        raise RuntimeError("engine exploded")

    monkeypatch.setattr("accelerator.runtime.runs.assess_workflow", explode)
    with RunService(tmp_path / "state") as service:
        run = service.create_run(service.preview(SAMPLE).snapshot_id)
        service.execute(run.id)

        finished = service.get_run(run.id)
        assert finished.status == "completed"
        assert finished.result is not None
        assert finished.result.failures == [
            "sample_alteryx_workflow.yxmd: unexpected RuntimeError: engine exploded"
        ]


def test_run_that_keeps_crashing_is_quarantined(tmp_path: Path) -> None:
    with RunService(tmp_path / "state") as service:
        run = service.create_run(service.preview(SAMPLE).snapshot_id)
        for attempt in range(1, MAX_RUN_ATTEMPTS + 1):
            assert service._claim(run.id) == attempt
            with service._connection() as connection:
                connection.execute("UPDATE runs SET lease=0 WHERE id=?", (run.id,))

        assert service._claim(run.id) is None
        quarantined = service.get_run(run.id)
        assert quarantined.status == "failed"
        assert f"abandoned after {MAX_RUN_ATTEMPTS} interrupted attempts" in (
            quarantined.error or ""
        )
        assert run.id not in service.pending()


def test_worker_loop_survives_a_run_that_raises(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    with RunService(tmp_path / "state") as service:
        snapshot = service.preview(SAMPLE).snapshot_id
        poison = service.create_run(snapshot)
        healthy = service.create_run(snapshot)
        original = service.execute

        def execute(identity: str) -> None:
            if identity == poison.id:
                raise RuntimeError("worker exploded")
            original(identity)

        monkeypatch.setattr(service, "execute", execute)
        monkeypatch.setattr(app.state, "run_service", service, raising=False)
        with TestClient(app, base_url="http://127.0.0.1"):
            deadline = time.monotonic() + 30
            while service.get_run(healthy.id).status != "completed":
                assert time.monotonic() < deadline, "a failing run starved the worker loop"
                time.sleep(0.1)
            assert service.get_run(poison.id).status == "queued"


def test_store_connections_honor_the_thirty_second_busy_timeout(tmp_path: Path) -> None:
    with RunService(tmp_path / "state") as service, service._connection() as connection:
        assert connection.execute("PRAGMA busy_timeout").fetchone()[0] == 30_000


def test_fresh_database_is_created_at_the_latest_schema(tmp_path: Path) -> None:
    store = RunStore(tmp_path / "state")
    with store.connection() as connection:
        assert connection.execute("PRAGMA user_version").fetchone()[0] == LATEST_SCHEMA_VERSION
        columns = {row["name"] for row in connection.execute("PRAGMA table_info(runs)")}
    store.close()
    assert {"attempts", "created_at"} <= columns


def _schema(database: Path) -> dict[str, list[tuple[str, str]]]:
    with closing(sqlite3.connect(database)) as connection:
        tables = [
            row[0]
            for row in connection.execute(
                "SELECT name FROM sqlite_master WHERE type='table' AND name NOT LIKE 'sqlite_%'"
            )
        ]
        return {
            table: [(row[1], row[2]) for row in connection.execute(f"PRAGMA table_info({table})")]
            for table in sorted(tables)
        }


def test_schema_four_database_migrates_in_place_and_keeps_its_rows(tmp_path: Path) -> None:
    state = tmp_path / "state"
    state.mkdir()
    with closing(sqlite3.connect(state / "runs.db")) as connection:
        connection.executescript(SHIPPED_SCHEMA_4)
        connection.execute(
            "INSERT INTO runs (id, snapshot, status, total) VALUES ('legacy', 'snap', 'queued', 1)"
        )
        connection.execute("INSERT INTO cache (key, result) VALUES ('k', 'v')")
        connection.commit()

    before = time.time()
    store = RunStore(state)
    with store.connection() as connection:
        assert connection.execute("PRAGMA user_version").fetchone()[0] == LATEST_SCHEMA_VERSION
        run = connection.execute("SELECT attempts, created_at, timings FROM runs").fetchone()
        cache = connection.execute("SELECT result, last_used FROM cache").fetchone()
    store.cache_put("ir_cache", "package", "{}")
    assert store.cache_get("ir_cache", "package") == "{}"
    store.close()
    fresh = RunStore(tmp_path / "fresh")
    fresh.close()

    assert run["attempts"] == 0
    assert run["timings"] is None
    assert run["created_at"] >= before
    assert (cache["result"], cache["last_used"] >= before) == ("v", True)
    assert _schema(state / "runs.db") == _schema(tmp_path / "fresh" / "runs.db")


def test_cache_reads_refresh_age_at_most_once_a_day(tmp_path: Path) -> None:
    store = RunStore(tmp_path / "state")
    store.cache_put("cache", "stale", "value")
    store.cache_put("cache", "recent", "value")
    now = time.time()
    with store.connection() as connection:
        connection.execute("UPDATE cache SET last_used=? WHERE key='stale'", (now - 2 * DAY,))
        connection.execute("UPDATE cache SET last_used=? WHERE key='recent'", (now - 3600,))

    assert store.cache_get("cache", "stale") == "value"
    assert store.cache_get("cache", "recent") == "value"
    assert store.cache_get("cache", "missing") is None
    with store.connection() as connection:
        used = {row["key"]: row["last_used"] for row in connection.execute("SELECT * FROM cache")}
    store.close()

    assert used["stale"] >= now
    assert used["recent"] == pytest.approx(now - 3600)


def test_garbage_collection_keeps_active_runs_and_their_snapshots(tmp_path: Path) -> None:
    state = tmp_path / "state"
    store = RunStore(state)
    now = time.time()
    old = now - 90 * DAY
    with store.connection() as connection:
        for snapshot, created in (("old", old), ("active", old), ("fresh", now)):
            connection.execute(
                "INSERT INTO snapshots (id, preview, created_at) VALUES (?, '{}', ?)",
                (snapshot, created),
            )
        for run, snapshot, status in (("done", "old", "completed"), ("busy", "active", "running")):
            connection.execute(
                "INSERT INTO runs (id, snapshot, status, total, created_at) VALUES (?, ?, ?, 1, ?)",
                (run, snapshot, status, old),
            )
        connection.execute("INSERT INTO neutral_assessments VALUES ('done', '{}')")
    for directory in ("snapshots/old", "snapshots/active", "publications/done/digest"):
        (state / directory).mkdir(parents=True)
        (state / directory / "artifact.json").write_text("x" * 10, encoding="utf-8")

    planned = store.collect_garbage(max_age_days=30, max_cache_bytes=10**9, dry_run=True)
    assert (planned.runs_deleted, planned.snapshots_deleted, planned.publications_deleted) == (
        1,
        1,
        1,
    )
    assert planned.bytes_freed == 20
    assert (state / "snapshots" / "old").is_dir()

    applied = store.collect_garbage(max_age_days=30, max_cache_bytes=10**9)
    with store.connection() as connection:
        runs = {row["id"] for row in connection.execute("SELECT id FROM runs")}
        snapshots = {row["id"] for row in connection.execute("SELECT id FROM snapshots")}
        neutral = connection.execute("SELECT COUNT(*) FROM neutral_assessments").fetchone()[0]
    store.close()

    assert applied.model_dump() == planned.model_copy(update={"dry_run": False}).model_dump()
    assert (runs, snapshots, neutral) == ({"busy"}, {"active", "fresh"}, 0)
    assert not (state / "snapshots" / "old").exists()
    assert not (state / "publications" / "done").exists()
    assert (state / "snapshots" / "active").is_dir()


def test_garbage_collection_evicts_cold_cache_rows_by_age_and_size(tmp_path: Path) -> None:
    store = RunStore(tmp_path / "state")
    now = time.time()
    ages = {"ancient": 90 * DAY, "cold": 300, "warm": 200, "hot": 100}
    for key in ages:
        store.cache_put("cache" if key != "warm" else "ir_cache", key, "x" * 100)
    with store.connection() as connection:
        for table in ("cache", "ir_cache"):
            for key, age in ages.items():
                connection.execute(f"UPDATE {table} SET last_used=? WHERE key=?", (now - age, key))

    report = store.collect_garbage(max_age_days=30, max_cache_bytes=150)
    with store.connection() as connection:
        remaining = {
            row["key"]
            for table in ("cache", "ir_cache")
            for row in connection.execute(f"SELECT key FROM {table}")
        }
    store.close()

    assert remaining == {"hot"}
    assert report.cache_rows_deleted == 3


def test_plugins_command_lists_the_catalog_and_fails_on_a_broken_plugin(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    runner = CliRunner()
    healthy = runner.invoke(cli_app, ["plugins"])
    assert healthy.exit_code == 0, healthy.output
    assert '"failed_count": 0' in healthy.output
    assert '"adapter_id": "alteryx"' in healthy.output

    monkeypatch.setattr(
        "etl_migration_core.sources.registry.entry_points",
        lambda **_kwargs: [FakeEntryPoint("broken", ImportError("No module named 'missing'"))],
    )
    broken = runner.invoke(cli_app, ["plugins"])
    assert broken.exit_code == 1
    assert "PLUGIN_LOAD_FAILED" in broken.output


def test_gc_command_honors_the_state_dir_environment_variable(tmp_path: Path) -> None:
    state = tmp_path / "custom-state"
    result = CliRunner().invoke(
        cli_app, ["gc", "--dry-run"], env={"ACCELERATOR_STATE_DIR": str(state)}
    )

    assert result.exit_code == 0, result.output
    assert '"dry_run": true' in result.output
    assert (state / "runs.db").is_file()


def test_broken_and_unapproved_plugins_are_reported_not_fatal(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(
        "etl_migration_core.sources.registry.entry_points",
        lambda **_kwargs: [
            FakeEntryPoint("broken", ImportError("No module named 'missing_plugin'")),
            FakeEntryPoint("flaky", FlakyAdapter()),
            FakeEntryPoint("unapproved", FlakyAdapter(adapter_id="unapproved")),
        ],
    )
    monkeypatch.setenv(PLUGIN_ALLOWLIST_ENV, " broken , flaky ")
    allowlist = plugin_allowlist_from_environment()
    assert allowlist == frozenset({"broken", "flaky"})

    registry = create_default_registry(load_entry_points=False)
    assert registry.load_entry_points(allowlist=allowlist, on_error="record") == 1
    with RunService(tmp_path / "state", source_registry=registry) as service:
        monkeypatch.setattr(app.state, "run_service", service, raising=False)
        monkeypatch.setattr(
            app.state,
            "target_registry",
            create_default_target_registry(load_entry_points=False),
            raising=False,
        )
        client = TestClient(app, base_url="http://127.0.0.1")
        plugins = client.get("/api/plugins").json()
        listed = client.get("/api/sources").json()["sources"]
        sources = {item["adapter_id"]: item for item in listed}

    assert plugins["allowlist"] == ["broken", "flaky"]
    assert plugins["failed_count"] == 1
    diagnostics = {item["code"]: item for item in plugins["diagnostics"]}
    assert diagnostics["PLUGIN_LOAD_FAILED"]["severity"] == "error"
    assert diagnostics["PLUGIN_LOAD_FAILED"]["stage"] == "plugin"
    assert "etl_migration.sources/broken" in diagnostics["PLUGIN_LOAD_FAILED"]["message"]
    assert diagnostics["PLUGIN_SKIPPED"]["severity"] == "info"
    outcomes = {item["name"]: item for item in plugins["plugins"]}
    assert outcomes["broken"]["status"] == "failed"
    assert "missing_plugin" in outcomes["broken"]["detail"]
    assert outcomes["flaky"]["status"] == "loaded"
    assert outcomes["flaky"]["provides"] == "flaky"
    assert outcomes["unapproved"]["status"] == "skipped"
    assert sources["flaky"]["origin"] == "plugin:flaky"
    assert sources["alteryx"]["origin"] == "builtin"


def _track_entry_points(
    monkeypatch: pytest.MonkeyPatch, module: str, entries: dict[str, object]
) -> list[str]:
    """Patch one registry's entry-point lookup and record which entry points get imported."""
    imported: list[str] = []

    class Tracking(FakeEntryPoint):
        def load(self) -> object:
            imported.append(self.name)
            return super().load()

    monkeypatch.setattr(
        f"{module}.entry_points",
        lambda **_kwargs: [Tracking(name, loaded) for name, loaded in entries.items()],
    )
    return imported


@pytest.mark.parametrize(
    "build",
    [
        lambda root: create_default_registry(),
        lambda root: PortfolioAssessmentApplication(),
        lambda root: FabricAssessmentApplication(),
        lambda root: RunService(root / "state").close(),
    ],
    ids=["registry", "portfolio-application", "fabric-application", "run-service"],
)
def test_plugin_allowlist_applies_to_every_default_source_registry(
    build: Callable[[Path], object], tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    imported = _track_entry_points(
        monkeypatch,
        "etl_migration_core.sources.registry",
        {"approved": FlakyAdapter(), "blocked": FlakyAdapter(adapter_id="blocked")},
    )
    monkeypatch.setenv(PLUGIN_ALLOWLIST_ENV, "approved")

    build(tmp_path)

    assert imported == ["approved"]


@pytest.mark.parametrize("factory", [create_default_target_registry, create_target_registry])
def test_plugin_allowlist_applies_to_both_target_registry_factories(
    factory: Callable[[], TargetPlatformRegistry], monkeypatch: pytest.MonkeyPatch
) -> None:
    imported = _track_entry_points(
        monkeypatch,
        "etl_migration_core.targets.registry",
        {"approved": ImportError("broken"), "blocked": ImportError("must never be imported")},
    )
    monkeypatch.setenv(PLUGIN_ALLOWLIST_ENV, "approved")

    registry = factory()

    assert imported == ["approved"]
    statuses = {result.name: result.status for result in registry.plugin_results}
    assert statuses == {"approved": "failed", "blocked": "skipped"}


@pytest.mark.parametrize(
    ("adapter", "reason"),
    [
        (FlakyAdapter(supported_extensions=(".DTSX",)), "invalid source extension"),
        (FlakyAdapter(adapter_version=cast(Any, 1)), "adapter_version"),
    ],
    ids=["uppercase-extension", "non-string-version"],
)
def test_plugin_with_invalid_metadata_is_isolated_and_the_host_keeps_working(
    adapter: FlakyAdapter, reason: str, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(
        "etl_migration_core.sources.registry.entry_points",
        lambda **_kwargs: [FakeEntryPoint("bad-plugin", adapter)],
    )

    registry = create_default_registry()
    with RunService(tmp_path / "state", source_registry=registry) as service:
        assert service.preview(SAMPLE).workflow_count == 1
    catalog = PluginHost(registry, create_target_registry(load_entry_points=False)).catalog()

    (result,) = registry.plugin_results
    assert (result.name, result.status) == ("bad-plugin", "failed")
    assert reason in (result.detail or "")
    assert catalog.failed_count == 1
    assert "flaky" not in {source.adapter_id for source in catalog.sources}


def test_builtin_discovery_metadata_is_identical_with_and_without_a_registry(
    tmp_path: Path,
) -> None:
    repository = Path(__file__).parent / "fixtures" / "informatica" / "basic_repository.xml"
    if not repository.exists():
        repository = next((Path(__file__).parent / "fixtures").rglob("basic_repository.xml"))
    folder = tmp_path / "input"
    folder.mkdir()
    (folder / "repository.xml").write_bytes(repository.read_bytes())
    (folder / "workflow.yxmd").write_bytes(SAMPLE.read_bytes())

    plain = DiscoveryService().discover(folder)
    with_plugins = DiscoveryService(
        source_registry=SourceAdapterRegistry((FlakyAdapter(),))
    ).discover(folder)

    assert plain.workflows == with_plugins.workflows
    assert {item.adapter_id for item in plain.workflows} == {
        "alteryx",
        "informatica-powercenter",
    }
    powercenter = next(item for item in plain.workflows if item.adapter_id != "alteryx")
    assert powercenter.adapter_version == "1.3.0"
    assert powercenter.parser_version == "1.3.0"


def test_settings_treat_blank_values_as_unset_and_parse_the_allowlist() -> None:
    assert Settings.from_environment({}) == Settings()

    configured = Settings.from_environment(
        {
            "ACCELERATOR_STATE_DIR": "state",
            "ACCELERATOR_ARTIFACT_DIR": "   ",
            "ACCELERATOR_PLUGIN_ALLOWLIST": "first, second",
            "ACCELERATOR_LOG_LEVEL": "debug",
        }
    )

    assert configured == Settings(
        state_dir=Path("state"),
        plugin_allowlist=frozenset({"first", "second"}),
        log_level="DEBUG",
    )


def test_configure_logging_is_idempotent_and_follows_the_current_stderr(
    capsys: pytest.CaptureFixture[str],
) -> None:
    configure_logging(Settings())
    configure_logging(Settings())

    logging.getLogger("accelerator.runtime.runs").info("stage timings are logged")

    assert capsys.readouterr().err.count("stage timings are logged") == 1


def test_runs_persist_stage_timings_and_expose_them_without_the_result(tmp_path: Path) -> None:
    with RunService(tmp_path / "state") as service:
        run = service.create_run(service.preview(SAMPLE).snapshot_id)
        assert service.get_run(run.id).timings is None
        service.execute(run.id)

        timings = service.get_run(run.id).timings
        assert timings is not None
        assert set(timings) == {"verify_ms", "assess_ms", "persist_ms", "total_ms"}
        assert timings["total_ms"] >= timings["assess_ms"] >= 0
        status = service.get_run_status(run.id)
        assert status.timings == timings
        assert "result" not in status.model_dump()


def test_single_workflow_reads_verify_only_the_requested_file(tmp_path: Path) -> None:
    sample_dir = Path(__file__).parents[1] / "alteryx-workflows"
    estate = tmp_path / "estate"
    estate.mkdir()
    (estate / "01.yxmd").write_bytes((sample_dir / "02_low_west_sample.yxmd").read_bytes())
    (estate / "02.yxmd").write_bytes((sample_dir / "sample_alteryx_workflow.yxmd").read_bytes())

    with RunService(tmp_path / "state") as service:
        preview = service.preview(estate)
        run = service.create_run(preview.snapshot_id)
        service.execute(run.id)
        assert service.get_run(run.id).status == "completed"

        # Tamper with workflow 1 only; reading workflow 0 still succeeds, reading 1 fails.
        Path(preview.workflows[1].source_path).write_text("tampered", encoding="utf-8")
        assert service.workflow_candidates(run.id, 0, "dataflow")
        assert service.evidence(run.id, workflow_index=0).workflows
        with pytest.raises(ValueError, match="Confirmed snapshot changed"):
            service.workflow_candidates(run.id, 1, "dataflow")
        with pytest.raises(ValueError, match="Confirmed snapshot changed"):
            service.evidence(run.id, workflow_index=1)


def test_ci_dispatchers_implement_shared_protocol() -> None:
    from accelerator.delivery.base import CiDeploymentDispatcher
    from accelerator.delivery.github import GitHubDeploymentService
    from accelerator.delivery.gitlab import GitLabDeploymentService

    github = GitHubDeploymentService(user_token="tok")
    gitlab = GitLabDeploymentService(token="tok", allowed_projects={"org/proj"})
    assert isinstance(github, CiDeploymentDispatcher)
    assert isinstance(gitlab, CiDeploymentDispatcher)
    assert github.provider_id == "github"
    assert gitlab.provider_id == "gitlab"

