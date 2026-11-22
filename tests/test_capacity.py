"""Tests for deterministic capacity profiling, estimation, and persistence."""

from dataclasses import dataclass
from pathlib import Path

import pytest
from pydantic import ValidationError

from accelerator.runtime.runs import RunService
from etl_migration_core.contracts.ir import SourcePlatform
from etl_target_fabric.capacity.model import (
    COUNT_KEYS,
    INFORMATICA_COUNT_KEYS,
    CapacitySettings,
    CapacityStaticProfile,
    CapacityUpdate,
    CapacityWorkflowInput,
    build_capacity_profile,
    estimate_capacity,
)


@dataclass
class CapacityAssessmentStub:
    path: str
    source_platform: SourcePlatform
    recommended_target: str
    capacity_profile: CapacityStaticProfile | None
    target_components: tuple[str, ...] = ()


def _profile(**counts: int) -> CapacityStaticProfile:
    values = dict.fromkeys(COUNT_KEYS, 0)
    values.update(counts)
    return CapacityStaticProfile(counts=values)


def test_profile_ports_reference_tool_mapping_without_runtime_workbook(
    tmp_path: Path,
) -> None:
    workflow = tmp_path / "profile.yxmd"
    workflow.write_text(
        """
        <AlteryxDocument>
          <Nodes>
            <Node ToolID="1">
              <GuiSettings Plugin="AlteryxBasePluginsGui.InputData.InputData" />
              <Properties><Configuration><File>orders.csv</File></Configuration></Properties>
            </Node>
            <Node ToolID="2"><GuiSettings Plugin="AlteryxBasePluginsGui.Filter.Filter" /></Node>
            <Node ToolID="3"><GuiSettings Plugin="AlteryxBasePluginsGui.Formula.Formula" /></Node>
            <Node ToolID="4">
              <GuiSettings Plugin="AlteryxBasePluginsGui.JSONParse.JSONParse" />
            </Node>
            <Node ToolID="5">
              <GuiSettings Plugin="AlteryxBasePluginsGui.OutputData.OutputData" />
            </Node>
          </Nodes>
        </AlteryxDocument>
        """,
        encoding="utf-8",
    )

    profile = build_capacity_profile(workflow)

    assert profile.counts["source"] == 1
    assert profile.counts["filter"] == 1
    assert profile.counts["calc"] == 1
    assert profile.counts["dest"] == 1
    assert profile.counts["database"] == 0
    assert profile.heavy_steps == 1


def test_estimate_matches_ported_reference_formula_and_requires_confirmation() -> None:
    assessment = CapacityAssessmentStub(
        path="orders.yxmd",
        source_platform=SourcePlatform.ALTERYX,
        recommended_target="Dataflow Gen2",
        capacity_profile=_profile(select=1, dest=1),
    )

    estimate = estimate_capacity(
        [assessment],
        {"orders.yxmd": CapacityWorkflowInput(workflow_path="orders.yxmd")},
        CapacitySettings(),
    )

    workflow = estimate.workflows[0]
    assert estimate.status == "inputs_required"
    assert workflow.query_seconds == pytest.approx(39.18196452145214)
    assert workflow.duration_driver == "minimum"
    assert workflow.row_volume_threshold == 20_731_198
    assert workflow.cu_seconds_per_run == pytest.approx(470.1835742574257)
    assert workflow.projected_cu_seconds_per_run == pytest.approx(474.88540999999995)
    assert workflow.monthly_cu_hours == pytest.approx(4.089291030555555)
    assert estimate.scenarios[0].recommended_sku == "F4"


def test_invalid_refresh_interval_is_rejected() -> None:
    with pytest.raises(ValidationError, match="must divide 1,440"):
        CapacityWorkflowInput(
            workflow_path="orders.yxmd",
            refresh_interval_minutes=100,
        )


def test_manual_rework_alteryx_and_informatica_are_modeled_and_missing_profile_excluded() -> None:
    manual = CapacityAssessmentStub(
        path="my_alteryx-workflow.yxmd",
        source_platform=SourcePlatform.ALTERYX,
        recommended_target="Manual rework",
        capacity_profile=build_capacity_profile(
            Path(__file__).parents[1] / "alteryx-workflows" / "my_alteryx-workflow.yxmd"
        ),
    )
    sample_manual = CapacityAssessmentStub(
        path="sample_alteryx_workflow.yxmd",
        source_platform=SourcePlatform.ALTERYX,
        recommended_target="Manual rework",
        capacity_profile=build_capacity_profile(
            Path(__file__).parents[1] / "alteryx-workflows" / "sample_alteryx_workflow.yxmd"
        ),
    )
    missing_profile = CapacityAssessmentStub(
        path="m_missing.xml",
        source_platform=SourcePlatform.INFORMATICA_POWERCENTER,
        recommended_target="Dataflow Gen2",
        target_components=("Dataflow Gen2",),
        capacity_profile=None,
    )

    estimate = estimate_capacity(
        [manual, sample_manual, missing_profile], {}, CapacitySettings()
    )

    assert estimate.status == "inputs_required"
    assert estimate.modeled_count == 2
    assert estimate.excluded_count == 1
    assert estimate.workflows[0].status == "unconfirmed"
    assert estimate.workflows[0].model_basis == "heuristic"
    assert (estimate.workflows[0].cu_seconds_per_run or 0) > 0
    assert estimate.workflows[1].status == "unconfirmed"
    assert (estimate.workflows[1].cu_seconds_per_run or 0) > 0
    assert estimate.workflows[2].status == "excluded"
    assert "unavailable" in (estimate.workflows[2].exclusion_reason or "")


def test_informatica_workbook_sample_parity() -> None:
    def info_profile(**counts: int) -> CapacityStaticProfile:
        values = dict.fromkeys(INFORMATICA_COUNT_KEYS, 0)
        values.update(counts)
        return CapacityStaticProfile(profile_kind="informatica", counts=values)

    samples = [
        (
            "wf_STG_Account_Transaction_Load",
            1440,
            100_000,
            {"source": 1, "dest": 1, "calc": 1, "database": 1},
            4.089291030555555,
        ),
        (
            "wf_STG_HFS_OCONNOR_DocDetails_Load",
            1440,
            100_000,
            {
                "source": 2,
                "dest": 8,
                "filter": 1,
                "calc": 11,
                "lookup": 6,
                "code": 1,
                "database": 2,
            },
            4.280379396469367,
        ),
    ]
    assessments = [
        CapacityAssessmentStub(
            path=name,
            source_platform=SourcePlatform.INFORMATICA_POWERCENTER,
            recommended_target="Dataflow Gen2",
            target_components=("Dataflow Gen2",),
            capacity_profile=info_profile(**counts),
        )
        for name, _, _, counts, _ in samples
    ]
    inputs = {
        name: CapacityWorkflowInput(
            workflow_path=name,
            refresh_interval_minutes=interval,
            source_rows_per_run=rows,
            confirmed=True,
        )
        for name, interval, rows, _, _ in samples
    }

    estimate = estimate_capacity(assessments, inputs, CapacitySettings())

    assert estimate.status == "planning_estimate"
    assert estimate.workflows[0].monthly_cu_hours == pytest.approx(samples[0][4])
    assert estimate.workflows[1].monthly_cu_hours == pytest.approx(samples[1][4])
    assert estimate.workflows[1].complexity_units == pytest.approx(7.84)


def test_run_service_estimates_powercenter_and_idmc_packages(tmp_path: Path) -> None:
    import shutil
    import zipfile

    fixtures = Path(__file__).parent / "fixtures"
    source = tmp_path / "estate"
    source.mkdir()
    shutil.copyfile(
        fixtures / "powercenter" / "basic_repository.xml",
        source / "basic_repository.xml",
    )
    idmc_zip = source / "idmc-export.zip"
    idmc_root = fixtures / "idmc" / "basic_export"
    with zipfile.ZipFile(idmc_zip, "w", compression=zipfile.ZIP_DEFLATED) as archive:
        for file_path in idmc_root.rglob("*"):
            if file_path.is_file():
                archive.write(file_path, file_path.relative_to(idmc_root).as_posix())

    service = RunService(tmp_path / "state")
    preview = service.preview(source)
    run = service.create_run(preview.snapshot_id)
    service.execute(run.id)

    unconfirmed = {
        item.workflow_path.split("!")[-1]: item for item in service.get_capacity(run.id).workflows
    }
    assert unconfirmed["Sales/wf_orders"].model_basis == "heuristic", (
        "before Fabric fit is confirmed, sizing sees only the static mapping"
    )

    service.ensure_fabric_fit(run.id)
    estimate = service.get_capacity(run.id)
    by_name = {item.workflow_path.split("!")[-1]: item for item in estimate.workflows}

    assert estimate.modeled_count == 3  # wf_orders, Sales/m_orders, Sales/tf_orders
    assert estimate.excluded_count == 1  # Sales/mt_orders thin wrapper
    assert by_name["Sales/wf_orders"].status == "unconfirmed"
    assert by_name["Sales/wf_orders"].model_basis == "calibrated"
    assert by_name["Sales/m_orders"].model_basis == "calibrated"
    assert by_name["Sales/tf_orders"].target_components == ["Fabric Pipeline"]
    assert (by_name["Sales/tf_orders"].pipeline_cu_seconds_per_run or 0) > 0
    assert by_name["Sales/mt_orders"].status == "excluded"
    assert "covered by its referenced mapping" in (
        by_name["Sales/mt_orders"].exclusion_reason or ""
    )


def test_mixed_and_notebook_routes_include_spark_by_default_and_toggle_autoscale() -> None:
    mixed = CapacityAssessmentStub(
        path="mixed.yxmd",
        source_platform=SourcePlatform.ALTERYX,
        recommended_target="Mixed Fabric solution",
        target_components=("Dataflow Gen2", "Fabric Notebook", "Fabric Pipeline"),
        capacity_profile=CapacityStaticProfile(
            counts={**dict.fromkeys(COUNT_KEYS, 0), "select": 2, "dest": 1},
            notebook_steps=1,
            total_steps=4,
        ),
    )
    notebook_only = CapacityAssessmentStub(
        path="nb.yxmd",
        source_platform=SourcePlatform.ALTERYX,
        recommended_target="Fabric Notebook",
        target_components=("Fabric Notebook",),
        capacity_profile=_profile(predictive=1),
    )
    inputs = {
        "mixed.yxmd": CapacityWorkflowInput(
            workflow_path="mixed.yxmd",
            spark_vcores=8,
            notebook_runtime_seconds=100,
            confirmed=True,
        ),
        "nb.yxmd": CapacityWorkflowInput(
            workflow_path="nb.yxmd",
            spark_vcores=16,
            notebook_runtime_seconds=120,
            confirmed=True,
        ),
    }

    in_capacity = estimate_capacity([mixed, notebook_only], inputs, CapacitySettings())
    autoscale = estimate_capacity(
        [mixed, notebook_only],
        inputs,
        CapacitySettings(spark_billing_mode="autoscale"),
    )

    mixed_cap = in_capacity.workflows[0]
    nb_cap = in_capacity.workflows[1]
    assert mixed_cap.model_basis == "heuristic"
    assert (mixed_cap.dataflow_cu_seconds_per_run or 0) > 0
    assert mixed_cap.notebook_cu_seconds_per_run == pytest.approx(400.0)
    assert mixed_cap.pipeline_cu_seconds_per_run == pytest.approx(40.0)
    assert nb_cap.notebook_cu_seconds_per_run == pytest.approx(960.0)
    assert in_capacity.autoscale_spark_monthly_cu_hours == 0.0
    assert in_capacity.heuristic_count == 2

    assert autoscale.daily_cu_seconds < in_capacity.daily_cu_seconds
    assert autoscale.autoscale_spark_monthly_cu_hours > 0.0
    assert autoscale.workflows[1].cu_seconds_per_run == 0.0
    assert (autoscale.workflows[1].autoscale_spark_monthly_cu_hours or 0) > 0.0


def test_run_service_persists_inputs_and_recomputes_estimate(tmp_path: Path) -> None:
    source = tmp_path / "source"
    source.mkdir()
    reference = (
        Path(__file__).parents[1]
        / "alteryx-workflows"
        / "11_multi_container_reconciliation.yxmd"
    )
    (source / "orders.yxmd").write_bytes(reference.read_bytes())
    service = RunService(tmp_path / "state")
    preview = service.preview(source)
    run = service.create_run(preview.snapshot_id)
    service.execute(run.id)

    initial = service.get_capacity(run.id)
    assert initial.status == "inputs_required"
    assert initial.workflows[0].source_rows_per_run == 1000

    updated = service.update_capacity(
        run.id,
        CapacityUpdate(
            inputs=[
                CapacityWorkflowInput(
                    workflow_path="orders.yxmd",
                    refresh_interval_minutes=60,
                    source_rows_per_run=50_000,
                    confirmed=True,
                )
            ]
        ),
    )
    restored = service.get_capacity(run.id)

    assert updated.status == "planning_estimate"
    assert restored.workflows[0].runs_per_day == 24
    assert "orders.yxmd" in service.export_capacity_csv(run.id)


def test_engine_only_node_uses_entry_point_and_heavy_steps_scale_with_rows(
    tmp_path: Path,
) -> None:
    workflow = tmp_path / "engine-heavy.yxmd"
    workflow.write_text(
        """
        <AlteryxDocument>
          <Nodes>
            <Node ToolID="1">
              <GuiSettings />
              <EngineSettings
                EngineDll="AlteryxBasePluginsEngine.dll"
                EngineDllEntryPoint="AlteryxSelect"
              />
            </Node>
            <Node ToolID="2">
              <GuiSettings Plugin="AlteryxBasePluginsGui.JSONParse.JSONParse" />
            </Node>
          </Nodes>
        </AlteryxDocument>
        """,
        encoding="utf-8",
    )

    profile = build_capacity_profile(workflow)
    assert profile.counts["select"] == 1
    assert profile.counts["other"] == 0
    assert profile.heavy_steps == 1

    assessment = CapacityAssessmentStub(
        path=workflow.name,
        source_platform=SourcePlatform.ALTERYX,
        recommended_target="Dataflow Gen2",
        capacity_profile=profile,
    )
    low = estimate_capacity(
        [assessment],
        {
            workflow.name: CapacityWorkflowInput(
                workflow_path=workflow.name,
                source_rows_per_run=1_000,
                confirmed=True,
            )
        },
        CapacitySettings(),
    )
    high = estimate_capacity(
        [assessment],
        {
            workflow.name: CapacityWorkflowInput(
                workflow_path=workflow.name,
                source_rows_per_run=50_000,
                confirmed=True,
            )
        },
        CapacitySettings(),
    )

    assert low.workflows[0].heavy_steps == 1
    assert (high.workflows[0].query_seconds or 0) > (low.workflows[0].query_seconds or 0)
    assert (high.workflows[0].cu_seconds_per_run or 0) > (
        low.workflows[0].cu_seconds_per_run or 0
    )


def test_workbook_four_workflow_golden_parity() -> None:
    samples = [
        (
            "df_loan_book_report",
            720,
            1,
            {
                "source": 11,
                "select": 43,
                "filter": 10,
                "calc": 66,
                "merge": 18,
                "append": 11,
                "group": 3,
                "sort": 13,
                "macro": 1,
            },
        ),
        (
            "df_lopr_position_limits_demo",
            720,
            22,
            {
                "source": 21,
                "select": 39,
                "filter": 51,
                "calc": 127,
                "merge": 44,
                "append": 28,
                "group": 3,
                "sort": 18,
                "macro": 3,
            },
        ),
        (
            "df_trace_exception_based_reviews",
            720,
            1,
            {
                "source": 4,
                "select": 50,
                "filter": 110,
                "calc": 77,
                "merge": 23,
                "append": 18,
                "group": 29,
                "sort": 21,
                "macro": 1,
            },
        ),
        (
            "df_market_access_quarterly_limit_review",
            720,
            34,
            {
                "source": 25,
                "dest": 19,
                "select": 125,
                "filter": 61,
                "calc": 135,
                "merge": 36,
                "merge3": 1,
                "append": 43,
                "group": 36,
                "sort": 14,
                "unique": 47,
                "sample": 1,
                "pivot": 56,
                "macro": 57,
            },
        ),
    ]
    assessments = [
        CapacityAssessmentStub(
            path=name,
            source_platform=SourcePlatform.ALTERYX,
            recommended_target="Dataflow Gen2",
            capacity_profile=_profile(**counts),
        )
        for name, _, _, counts in samples
    ]
    inputs = {
        name: CapacityWorkflowInput(
            workflow_path=name,
            refresh_interval_minutes=interval,
            source_rows_per_run=rows,
            confirmed=True,
        )
        for name, interval, rows, _ in samples
    }

    estimate = estimate_capacity(assessments, inputs, CapacitySettings())

    assert estimate.status == "planning_estimate"
    assert estimate.monthly_cu_hours == pytest.approx(275.00345688796176)
    assert estimate.daily_cu_seconds == pytest.approx(31935.885316021362)
    assert estimate.background_cu == pytest.approx(0.36962830226876575)
    assert [(s.name, s.recommended_sku) for s in estimate.scenarios] == [
        ("Optimized", "F32"),
        ("Balance", "F64"),
        ("Peak", "F64"),
    ]
    assert [s.required_cu for s in estimate.scenarios] == pytest.approx(
        [23.936380494971072, 38.88142801083667, 53.826475526702275]
    )


def test_disabled_alteryx_container_tools_are_excluded_from_capacity_profile(
    tmp_path: Path,
) -> None:
    from etl_target_fabric.assessment.workflow import assess_workflow

    workflow = tmp_path / "disabled.yxmd"
    workflow.write_text(
        """
        <AlteryxDocument>
          <Nodes>
            <Node ToolID="1">
              <GuiSettings Plugin="AlteryxBasePluginsGui.InputData.InputData" />
              <Properties><Configuration><File>orders.csv</File></Configuration></Properties>
            </Node>
            <Node ToolID="2">
              <GuiSettings Plugin="AlteryxGuiToolkit.ToolContainer.ToolContainer" />
              <Properties>
                <Configuration><Disabled value="True" /></Configuration>
              </Properties>
              <ChildNodes>
                <Node ToolID="3">
                  <GuiSettings Plugin="AlteryxBasePluginsGui.JSONParse.JSONParse" />
                </Node>
                <Node ToolID="4">
                  <GuiSettings Plugin="AlteryxBasePluginsGui.Formula.Formula" />
                </Node>
              </ChildNodes>
            </Node>
            <Node ToolID="5">
              <GuiSettings Plugin="AlteryxBasePluginsGui.OutputData.OutputData" />
            </Node>
          </Nodes>
        </AlteryxDocument>
        """,
        encoding="utf-8",
    )

    assessment = assess_workflow(workflow)
    assert assessment.capacity_profile is not None
    assert assessment.capacity_profile.counts["source"] == 1
    assert assessment.capacity_profile.counts["dest"] == 1
    assert assessment.capacity_profile.counts["calc"] == 0
    assert assessment.capacity_profile.heavy_steps == 0
    assert assessment.capacity_profile == build_capacity_profile(workflow)
