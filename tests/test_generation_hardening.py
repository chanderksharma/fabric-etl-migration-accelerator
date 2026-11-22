"""Tier-0 generation isolation, candidate cache, and additive generation jobs."""

from __future__ import annotations

from pathlib import Path

import pytest

from accelerator.runtime.runs import RunService
from etl_migration_core.contracts.artifacts import ArtifactSet
from etl_migration_core.contracts.spi import IR_SPI_VERSION, TargetPlatformInfo
from etl_migration_core.plugins import require_compatible_spi
from etl_migration_core.targets.registry import TargetPlatformRegistry
from etl_target_fabric.compilers.alteryx import generate_candidate

_LINEAR = """<?xml version="1.0"?>
<AlteryxDocument yxmdVer="2024.1">
  <Nodes>
    <Node ToolID="1">
      <GuiSettings Plugin="AlteryxBasePluginsGui.TextInput.TextInput">
        <Position x="48" y="54" />
      </GuiSettings>
      <Properties>
        <Configuration>
          <NumRows value="1" />
          <Fields><Field name="Amount" /></Fields>
          <Data><r><c>1</c></r></Data>
        </Configuration>
      </Properties>
      <EngineSettings
        EngineDll="AlteryxBasePluginsEngine.dll"
        EngineDllEntryPoint="AlteryxTextInput" />
    </Node>
    <Node ToolID="2">
      <GuiSettings Plugin="{plugin}">
        <Position x="168" y="54" />
      </GuiSettings>
      <Properties><Configuration>{configuration}</Configuration></Properties>
      <EngineSettings EngineDll="AlteryxBasePluginsEngine.dll" EngineDllEntryPoint="{entry}" />
    </Node>
  </Nodes>
  <Connections>
    <Connection>
      <Origin ToolID="1" Connection="Output" />
      <Destination ToolID="2" Connection="Input" />
    </Connection>
  </Connections>
</AlteryxDocument>
"""


def _completed_run(tmp_path: Path, workflows: dict[str, str]) -> tuple[RunService, str]:
    source = tmp_path / "estate"
    source.mkdir()
    for name, body in workflows.items():
        (source / name).write_text(body, encoding="utf-8")
    service = RunService(tmp_path / "state", artifact_root=tmp_path / "artifacts")
    run = service.create_run(service.preview(source).snapshot_id)
    service.execute(run.id)
    assert service.get_run(run.id).status == "completed"
    return service, run.id


def test_missing_linear_tool_configuration_scaffolds_instead_of_raising(tmp_path: Path) -> None:
    cases = (
        ("AlteryxBasePluginsGui.Sort.Sort", "AlteryxSort", "", "SortInfo"),
        ("AlteryxBasePluginsGui.Formula.Formula", "AlteryxFormula", "", "FormulaFields"),
        ("AlteryxBasePluginsGui.Unique.Unique", "AlteryxUnique", "", "UniqueFields"),
        (
            "AlteryxBasePluginsGui.RegEx.RegEx",
            "AlteryxRegEx",
            "<Method>ParseComplex</Method>",
            "ParseComplex",
        ),
    )
    for plugin, entry, configuration, key in cases:
        path = tmp_path / f"{key}.yxmd"
        path.write_text(
            _LINEAR.format(plugin=plugin, entry=entry, configuration=configuration),
            encoding="utf-8",
        )
        candidate = generate_candidate(path, "notebook")
        assert candidate.validation_state == "scaffold"
        assert any(f"missing {key}" in diagnostic for diagnostic in candidate.diagnostics)


def test_mixed_estate_keeps_the_good_workflow_and_reraises_os_error(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    good = _LINEAR.format(
        plugin="AlteryxBasePluginsGui.Sort.Sort",
        entry="AlteryxSort",
        configuration="<SortInfo><Field field='Amount' order='Ascending' /></SortInfo>",
    )
    bad = good.replace("AlteryxSort", "AlteryxSort", 1) + "<!-- BAD-MARKER -->"
    service, identity = _completed_run(
        tmp_path,
        {"good.yxmd": good, "bad.yxmd": bad},
    )
    original = generate_candidate

    def fail_bad(path: Path, target: str, graph: object = None) -> object:
        if "BAD-MARKER" in path.read_text(encoding="utf-8"):
            raise RuntimeError("compiler fault")
        return original(path, target, graph=graph)  # type: ignore[arg-type]

    monkeypatch.setattr("accelerator.runtime.runs.generate_candidate", fail_bad)
    written = service.write_artifacts(identity, "notebook")
    blocked = [item for item in written.candidates if item.validation_state == "blocked"]
    kept = [item for item in written.candidates if item.validation_state != "blocked"]
    assert blocked and "unexpected generation fault" in blocked[0].diagnostics[0]
    assert kept

    def fail_os(path: Path, target: str, graph: object = None) -> object:
        raise OSError("disk")

    monkeypatch.setattr("accelerator.runtime.runs.generate_candidate", fail_os)
    with pytest.raises(OSError, match="disk"):
        service.write_artifacts(identity, "notebook")
    service.close()


def test_generation_job_caches_candidates_without_writing_artifacts(tmp_path: Path) -> None:
    body = _LINEAR.format(
        plugin="AlteryxBasePluginsGui.Sort.Sort",
        entry="AlteryxSort",
        configuration="<SortInfo><Field field='Amount' order='Ascending' /></SortInfo>",
    )
    service, identity = _completed_run(tmp_path, {"orders.yxmd": body})
    job = service.create_generation_job(identity, "notebook")
    service.execute_generation_job(job.id)
    completed = service.generation_jobs(identity)[0]
    assert completed.status == "completed"
    assert completed.candidates
    assert not (tmp_path / "artifacts").exists()
    preview = service.workflow_candidates(identity, 0, "notebook")
    assert preview[0].code_sha256 == completed.candidates[0].code_sha256
    with service._connection() as connection:
        rows = connection.execute("SELECT key FROM cache WHERE key LIKE 'candidate:%'").fetchall()
        artifacts = connection.execute(
            "SELECT key FROM cache WHERE key LIKE 'artifact:candidate:%'"
        ).fetchall()
    assert rows and artifacts
    projected = ArtifactSet.model_validate_json(
        service._store.cache_get("cache", artifacts[0]["key"]) or ""
    )
    assert projected.files == ()
    service.close()


def test_spi_handshake_rejects_only_an_incompatible_declaration() -> None:
    class Current:
        platform_id = "example"
        display_name = "Example"
        provider_version = "1.0.0"
        supported_ir_versions = ("1.0.0",)
        implemented = True
        capabilities = ()
        description = "Current SPI"

        def evaluator(self) -> None:
            return None

        def info(self) -> TargetPlatformInfo:
            return TargetPlatformInfo(
                platform_id=self.platform_id,
                display_name=self.display_name,
                provider_version=self.provider_version,
                supported_ir_versions=self.supported_ir_versions,
                implemented=True,
                status="ready",
                capabilities=self.capabilities,
                description=self.description,
            )

    require_compatible_spi(Current(), "example")
    registry = TargetPlatformRegistry()
    registry.register(Current())
    incompatible = Current()
    incompatible.spi_version = "2.0.0"  # type: ignore[attr-defined]
    with pytest.raises(ValueError, match=IR_SPI_VERSION):
        registry.register(incompatible)
