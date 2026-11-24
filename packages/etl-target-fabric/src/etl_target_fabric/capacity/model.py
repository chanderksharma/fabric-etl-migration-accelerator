"""Versioned Alteryx & Informatica to Fabric capacity planning model."""

from __future__ import annotations

import csv
import io
import re
from collections.abc import Iterable, Sequence
from pathlib import Path
from typing import Literal, Protocol

from defusedxml import ElementTree as SafeElementTree
from defusedxml.common import DefusedXmlException
from pydantic import BaseModel, Field, model_validator

from etl_migration_core.contracts.ir import (
    AssetType,
    EtlAsset,
    EtlNode,
    EtlPackage,
    NodeKind,
    SourcePlatform,
)
from etl_migration_core.sources.alteryx.graph import GraphNode, WorkflowGraph, parse_graph

CAPACITY_MODEL_VERSION = "3.1.0"
DEFAULT_REFRESH_INTERVAL_MINUTES = 1440
DEFAULT_SOURCE_ROWS_PER_RUN = 1000
DEFAULT_SPARK_VCORES = 8
FABRIC_COMPONENTS = ("Dataflow Gen2", "Fabric Notebook", "Fabric Pipeline")
ELIGIBLE_TARGETS = frozenset({*FABRIC_COMPONENTS, "Mixed Fabric solution", "Manual rework"})
SUPPORTED_PLATFORMS = frozenset(
    {
        SourcePlatform.ALTERYX,
        SourcePlatform.INFORMATICA_POWERCENTER,
        SourcePlatform.INFORMATICA_IDMC,
    }
)
SKU_TIERS = (2, 4, 8, 16, 32, 64, 128, 256, 512, 1024, 2048, 4096, 8192)
COUNT_KEYS = (
    "source",
    "folder",
    "dest",
    "report",
    "select",
    "clean",
    "filter",
    "calc",
    "merge",
    "merge3",
    "find",
    "append",
    "group",
    "sort",
    "unique",
    "sample",
    "pivot",
    "unpivot",
    "arrange",
    "macro",
    "spatial",
    "predictive",
    "api",
    "database",
    "other",
)
WEIGHTS = dict(
    zip(
        COUNT_KEYS,
        (
            0.90,
            0.90,
            0.07,
            0.07,
            0.04,
            0.04,
            0.04,
            0.05,
            0.85,
            0.85,
            0.21,
            0.08,
            0.05,
            0.05,
            0.10,
            0.18,
            0.08,
            0.14,
            0.14,
            0.45,
            0.89,
            1.06,
            0.53,
            0.07,
            0.06,
        ),
        strict=True,
    )
)
INFORMATICA_COUNT_KEYS = (
    "source",
    "folder",
    "dest",
    "filter",
    "calc",
    "merge",
    "merge3",
    "lookup",
    "group",
    "sort",
    "reshape",
    "update",
    "code",
    "api",
    "database",
    "other",
)
INFORMATICA_WEIGHTS = dict(
    zip(
        INFORMATICA_COUNT_KEYS,
        (
            0.90,
            0.90,
            0.07,
            0.04,
            0.05,
            0.85,
            0.85,
            0.65,
            0.10,
            0.08,
            0.12,
            0.35,
            0.85,
            0.53,
            0.07,
            0.06,
        ),
        strict=True,
    )
)


class CapacityStaticProfile(BaseModel):
    """Tool/transformation profile derived from immutable Alteryx or Informatica source."""

    model_version: str = CAPACITY_MODEL_VERSION
    profile_kind: Literal["alteryx", "informatica"] = "alteryx"
    counts: dict[str, int]
    heavy_steps: int = 0
    notebook_steps: int = 0
    pipeline_steps: int = 0
    total_steps: int = 0
    covered_by_linked_mapping: bool = False

    @model_validator(mode="after")
    def validate_counts(self) -> CapacityStaticProfile:
        expected = (
            set(INFORMATICA_COUNT_KEYS)
            if self.profile_kind == "informatica"
            else set(COUNT_KEYS)
        )
        if set(self.counts) != expected:
            raise ValueError("Capacity profile count keys do not match the model")
        if (
            self.heavy_steps < 0
            or self.notebook_steps < 0
            or self.pipeline_steps < 0
            or self.total_steps < 0
            or any(value < 0 for value in self.counts.values())
        ):
            raise ValueError("Capacity profile counts cannot be negative")
        return self


class CapacityAssessment(Protocol):
    """Assessment fields consumed by the capacity engine."""

    @property
    def path(self) -> str: ...

    @property
    def source_platform(self) -> SourcePlatform: ...

    @property
    def recommended_target(self) -> str: ...

    @property
    def target_components(self) -> Sequence[str]: ...

    @property
    def capacity_profile(self) -> CapacityStaticProfile | None: ...


class CapacityWorkflowInput(BaseModel):
    """Mutable operational inputs supplied or confirmed by an analyst."""

    workflow_path: str
    refresh_interval_minutes: int = Field(
        default=DEFAULT_REFRESH_INTERVAL_MINUTES,
        ge=1,
        le=1440,
    )
    source_rows_per_run: int = Field(
        default=DEFAULT_SOURCE_ROWS_PER_RUN,
        ge=1,
    )
    spark_vcores: int = Field(default=DEFAULT_SPARK_VCORES, ge=2, le=512)
    notebook_runtime_seconds: int | None = Field(default=None, ge=1, le=86400)
    confirmed: bool = False

    @model_validator(mode="after")
    def validate_interval(self) -> CapacityWorkflowInput:
        if 1440 % self.refresh_interval_minutes:
            raise ValueError("Refresh interval must divide 1,440 minutes")
        return self


class CapacitySettings(BaseModel):
    """Portfolio assumptions carried from the reference capacity workbook."""

    model_version: str = CAPACITY_MODEL_VERSION
    days_per_month: int = Field(default=31, ge=1, le=366)
    target_utilization: float = Field(default=0.8, gt=0, le=1)
    capacity_floor_cu: float = Field(default=0, ge=0)
    burst_window_minutes: int = Field(default=5, ge=1, le=1440)
    balance_weight: float = Field(default=0.5, ge=0, le=1)
    active_users_per_day: int = Field(default=1, ge=0)
    average_active_hours_per_user: float = Field(default=2, ge=0, le=24)
    peak_concurrent_users: int = Field(default=1, ge=0)
    cu_per_active_user: float = Field(default=0.3, ge=0)
    interactive_peak_factor: float = Field(default=2, ge=0)

    seconds_per_complexity_element: float = Field(
        default=5.231236918751955,
        gt=0,
    )
    minimum_seconds_per_output: float = Field(
        default=39.18196452145214,
        gt=0,
    )
    initial_cu_rate: float = Field(default=12, gt=0)
    subsequent_cu_rate: float = Field(default=1.5, gt=0)
    cu_rate_threshold_seconds: float = Field(default=600, gt=0)
    extra_output_overlap: float = Field(default=0, ge=0)
    projection_variation: float = Field(default=0.01, ge=0)
    seconds_per_heavy_step_per_thousand_rows: float = Field(
        default=1.255806863185154,
        ge=0,
    )
    seconds_per_hundred_rows: float = Field(default=0.000189, ge=0)
    calibration_multiplier: float = Field(default=1, gt=0)
    spark_billing_mode: Literal["capacity", "autoscale"] = "capacity"
    pipeline_orchestration_cu_seconds_per_activity: float = Field(default=20.0, ge=0)
    pipeline_copy_base_seconds: float = Field(default=15.0, ge=0)
    pipeline_copy_cu_per_second: float = Field(default=1.5, ge=0)


class CapacityScenario(BaseModel):
    """One portfolio concurrency scenario."""

    name: Literal["Optimized", "Balance", "Peak"]
    required_cu: float
    recommended_sku: str


class CapacityWorkflowEstimate(BaseModel):
    """Capacity contribution and input status for one assessed workflow."""

    workflow_path: str
    recommended_target: str = "Dataflow Gen2"
    target_components: list[str] = Field(default_factory=list)
    model_basis: Literal["calibrated", "heuristic"] | None = None
    status: Literal["estimated", "unconfirmed", "excluded"]
    exclusion_reason: str | None = None
    refresh_interval_minutes: int
    source_rows_per_run: int
    spark_vcores: int = DEFAULT_SPARK_VCORES
    notebook_runtime_seconds: int | None = None
    effective_notebook_runtime_seconds: float | None = None
    confirmed: bool
    runs_per_day: float | None = None
    complexity_units: float | None = None
    heavy_steps: int = 0
    duration_driver: Literal["minimum", "complexity", "row_volume"] | None = None
    row_volume_threshold: int | None = None
    query_seconds: float | None = None
    dataflow_cu_seconds_per_run: float | None = None
    notebook_cu_seconds_per_run: float | None = None
    pipeline_cu_seconds_per_run: float | None = None
    cu_seconds_per_run: float | None = None
    projected_cu_seconds_per_run: float | None = None
    monthly_cu_hours: float | None = None
    autoscale_spark_monthly_cu_hours: float | None = None


class CapacityPortfolioEstimate(BaseModel):
    """Versioned capacity result for an assessment run."""

    model_version: str = CAPACITY_MODEL_VERSION
    status: Literal["inputs_required", "planning_estimate", "not_available"]
    settings: CapacitySettings
    workflow_count: int
    eligible_count: int
    modeled_count: int
    excluded_count: int
    unconfirmed_count: int
    calibrated_count: int = 0
    heuristic_count: int = 0
    coverage_percent: float
    monthly_cu_hours: float
    daily_cu_seconds: float
    background_cu: float
    autoscale_spark_daily_cu_seconds: float = 0.0
    autoscale_spark_monthly_cu_hours: float = 0.0
    target_counts: dict[str, int] = Field(default_factory=dict)
    scenarios: list[CapacityScenario]
    workflows: list[CapacityWorkflowEstimate]
    assumptions: list[str]


class CapacityUpdate(BaseModel):
    """Capacity input/settings update from the analyst UI."""

    inputs: list[CapacityWorkflowInput] = Field(default_factory=list)
    settings: CapacitySettings | None = None


def build_capacity_profile(
    path: Path,
    *,
    graph: WorkflowGraph | None = None,
) -> CapacityStaticProfile:
    """Classify Alteryx source nodes using the reference calculator mapping."""
    resolved_graph = graph if graph is not None else parse_graph(path)
    counts = dict.fromkeys(COUNT_KEYS, 0)
    databases: set[str] = set()
    heavy_steps = 0
    notebook_steps = 0
    pipeline_steps = 0
    total_steps = 0
    for node in resolved_graph.nodes:
        if node.disabled:
            continue
        bucket = _classify_node(node)
        if bucket == "skip":
            continue
        total_steps += 1
        token = _token(node)
        if bucket in {"predictive", "spatial", "macro"} or token in {
            "python",
            "rtool",
            "multirowformula",
        }:
            notebook_steps += 1
        if bucket == "api" or token in {
            "download",
            "dynamicinput",
            "runcommand",
            "email",
            "detour",
            "controlcontainer",
        }:
            pipeline_steps += 1
        if bucket == "heavy":
            heavy_steps += 1
        else:
            counts[bucket] += 1
        if bucket == "source" and token != "textinput":
            key = _database_key(node)
            if key:
                databases.add(key)
    counts["database"] = len(databases)
    return CapacityStaticProfile(
        profile_kind="alteryx",
        counts=counts,
        heavy_steps=heavy_steps,
        notebook_steps=notebook_steps,
        pipeline_steps=pipeline_steps,
        total_steps=total_steps,
    )


def build_alteryx_ir_capacity_profile(asset: EtlAsset) -> CapacityStaticProfile:
    """Classify Alteryx canonical IR nodes without re-reading or re-parsing XML from disk."""
    graph_nodes = tuple(
        GraphNode(
            id=node.native_id,
            plugin=node.native_type or "",
            name=node.operation,
            configuration={
                key: value
                for key, value in node.properties.items()
                if isinstance(value, str) and key not in {"macro", "engine_entry"}
            },
            disabled=node.disabled,
            engine_entry=(
                str(node.properties["engine_entry"])
                if isinstance(node.properties.get("engine_entry"), str)
                else ""
            ),
            macro=(
                str(node.properties["macro"])
                if isinstance(node.properties.get("macro"), str)
                else ""
            ),
            issues=node.issues,
            label=node.label,
        )
        for graph in asset.mapping_graphs
        for node in graph.nodes
    )
    synthetic = WorkflowGraph(
        nodes=graph_nodes,
        edges=(),
        dependencies=(),
        data_sources=(),
        sha256="",
    )
    return build_capacity_profile(Path(asset.name), graph=synthetic)


def build_informatica_capacity_profile(
    package: EtlPackage,
    asset: EtlAsset,
) -> CapacityStaticProfile:
    """Classify Informatica PowerCenter or IDMC nodes using the reference calculator mapping."""
    counts = dict.fromkeys(INFORMATICA_COUNT_KEYS, 0)
    databases: set[str] = set()
    heavy_steps = 0
    notebook_steps = 0
    pipeline_steps = 0
    total_steps = 0

    is_idmc = package.source_platform is SourcePlatform.INFORMATICA_IDMC
    raw_cap = asset.metadata.get("capacity")
    cap_meta = raw_cap if isinstance(raw_cap, dict) else {}
    raw_indirect = cap_meta.get("indirect_instances")
    indirect_instances = (
        {str(item) for item in raw_indirect}
        if isinstance(raw_indirect, list)
        else set()
    )
    raw_dbs = cap_meta.get("databases")
    if isinstance(raw_dbs, list):
        databases.update(str(item) for item in raw_dbs if item)

    for graph in asset.mapping_graphs:
        for node in graph.nodes:
            bucket = _classify_informatica_node(node, is_idmc=is_idmc)
            if bucket == "skip":
                continue
            if node.name in indirect_instances:
                if bucket == "xmlsource":
                    bucket = "xmlfolder"
                elif bucket == "source":
                    bucket = "folder"
            heavy_delta, nb_delta = _tally_informatica_bucket(counts, bucket)
            total_steps += 1
            heavy_steps += heavy_delta
            notebook_steps += nb_delta
            conn_info = node.properties.get("Connection Information")
            if isinstance(conn_info, str):
                db = _informatica_db_key(conn_info)
                if db:
                    databases.add(db)

    raw_mapplet_steps = cap_meta.get("mapplet_steps")
    if isinstance(raw_mapplet_steps, list):
        for step in raw_mapplet_steps:
            if not isinstance(step, dict):
                continue
            op = str(step.get("operation", "")).casefold()
            tmpl = str(step.get("template_name", "")).casefold()
            groups_val = step.get("input_groups", 2)
            groups = groups_val if isinstance(groups_val, int) else 2
            bucket = _classify_informatica_operation(op, tmpl, groups, is_idmc=is_idmc)
            if bucket == "skip":
                continue
            heavy_delta, nb_delta = _tally_informatica_bucket(counts, bucket)
            total_steps += 1
            heavy_steps += heavy_delta
            notebook_steps += nb_delta

    raw_commands = cap_meta.get("command_tasks")
    command_tasks = raw_commands if isinstance(raw_commands, int) else 0
    if not command_tasks and asset.orchestration_graph is not None:
        command_tasks = sum(
            1
            for node in asset.orchestration_graph.nodes
            if node.operation == "command" and not node.disabled
        )
    if command_tasks > 0:
        counts["other"] += command_tasks
        pipeline_steps += command_tasks
        total_steps += command_tasks

    if asset.orchestration_graph is not None:
        pipeline_steps += sum(
            1
            for node in asset.orchestration_graph.nodes
            if node.kind is NodeKind.TASK
            and node.operation not in {"session", "command"}
            and not node.disabled
        )

    counts["database"] = len(databases)
    linked_mapping_ids = {
        item.native_id
        for item in package.assets
        if item.asset_type is AssetType.MAPPING
    }
    covered_by_linked_mapping = (
        asset.asset_type is AssetType.MAPPING_TASK
        and not asset.mapping_graphs
        and any(
            dep.kind == "mapping_task_mapping" and dep.target_native_id in linked_mapping_ids
            for dep in asset.dependencies
        )
    )
    return CapacityStaticProfile(
        profile_kind="informatica",
        counts=counts,
        heavy_steps=heavy_steps,
        notebook_steps=notebook_steps,
        pipeline_steps=pipeline_steps,
        total_steps=total_steps,
        covered_by_linked_mapping=covered_by_linked_mapping,
    )


def estimate_capacity(
    assessments: Iterable[CapacityAssessment],
    inputs: dict[str, CapacityWorkflowInput],
    settings: CapacitySettings,
) -> CapacityPortfolioEstimate:
    """Calculate workflow contributions and portfolio concurrency scenarios."""
    workflows: list[CapacityWorkflowEstimate] = []
    daily_cu_seconds = 0.0
    monthly_cu_hours = 0.0
    autoscale_spark_daily_cu_seconds = 0.0
    autoscale_spark_monthly_cu_hours = 0.0
    largest_run = 0.0
    peak_window_cu_seconds = 0.0
    eligible_count = 0
    modeled_count = 0
    unconfirmed_count = 0
    calibrated_count = 0
    heuristic_count = 0
    target_counts: dict[str, int] = {}

    for assessment in assessments:
        path = str(assessment.path)
        profile = assessment.capacity_profile
        input_value = inputs.get(path, CapacityWorkflowInput(workflow_path=path))
        components = _effective_components(assessment)
        exclusion = _capacity_exclusion(assessment, profile, components)
        if exclusion:
            workflows.append(
                CapacityWorkflowEstimate(
                    workflow_path=path,
                    recommended_target=assessment.recommended_target,
                    target_components=components,
                    status="excluded",
                    exclusion_reason=exclusion,
                    refresh_interval_minutes=input_value.refresh_interval_minutes,
                    source_rows_per_run=input_value.source_rows_per_run,
                    spark_vcores=input_value.spark_vcores,
                    notebook_runtime_seconds=input_value.notebook_runtime_seconds,
                    confirmed=input_value.confirmed,
                )
            )
            continue
        eligible_count += 1
        modeled_count += 1
        if not input_value.confirmed:
            unconfirmed_count += 1
        assert isinstance(profile, CapacityStaticProfile)
        estimate = _estimate_workflow(
            path,
            assessment.recommended_target,
            components,
            profile,
            input_value,
            settings,
        )
        workflows.append(estimate)
        target_counts[estimate.recommended_target] = (
            target_counts.get(estimate.recommended_target, 0) + 1
        )
        if estimate.model_basis == "calibrated":
            calibrated_count += 1
        else:
            heuristic_count += 1
        assert estimate.projected_cu_seconds_per_run is not None
        assert estimate.runs_per_day is not None
        assert estimate.monthly_cu_hours is not None
        assert estimate.autoscale_spark_monthly_cu_hours is not None
        daily_cu_seconds += estimate.projected_cu_seconds_per_run * estimate.runs_per_day
        monthly_cu_hours += estimate.monthly_cu_hours
        if settings.spark_billing_mode == "autoscale" and estimate.notebook_cu_seconds_per_run:
            autoscale_spark_daily_cu_seconds += (
                estimate.notebook_cu_seconds_per_run
                * (1 + settings.projection_variation)
                * estimate.runs_per_day
            )
            autoscale_spark_monthly_cu_hours += estimate.autoscale_spark_monthly_cu_hours
        largest_run = max(largest_run, estimate.projected_cu_seconds_per_run)
        burst_factor = max(
            settings.burst_window_minutes * estimate.runs_per_day / 1440,
            1,
        )
        peak_window_cu_seconds += estimate.projected_cu_seconds_per_run * burst_factor

    background_cu = daily_cu_seconds / 86400
    interactive_average = (
        settings.active_users_per_day
        * settings.average_active_hours_per_user
        * 3600
        * settings.cu_per_active_user
        / 86400
    )
    interactive_peak = (
        settings.peak_concurrent_users
        * settings.cu_per_active_user
        * settings.interactive_peak_factor
    )
    average_need = (background_cu + interactive_average) / settings.target_utilization
    window_seconds = settings.burst_window_minutes * 60
    optimized = max(
        average_need,
        largest_run / window_seconds + interactive_peak,
        settings.capacity_floor_cu,
    )
    peak = max(
        average_need,
        peak_window_cu_seconds / window_seconds + interactive_peak,
        settings.capacity_floor_cu,
    )
    balance = optimized + (peak - optimized) * settings.balance_weight
    scenarios = [
        _scenario("Optimized", optimized),
        _scenario("Balance", balance),
        _scenario("Peak", peak),
    ]
    excluded_count = len(workflows) - modeled_count
    workflow_count = len(workflows)
    coverage = modeled_count / workflow_count * 100 if workflow_count else 0
    if not modeled_count:
        status: Literal["inputs_required", "planning_estimate", "not_available"] = (
            "not_available"
        )
    elif unconfirmed_count:
        status = "inputs_required"
    else:
        status = "planning_estimate"
    assumptions = [
        "Supports assessed Alteryx and Informatica (PowerCenter & IDMC) workflows across "
        "Dataflow Gen2, Notebook, Pipeline, Mixed, and indicative Manual rework.",
        "Dataflow Gen2 uses the calibrated workbook model with platform-specific step "
        "weights; Notebook (vCores/2), Pipeline, and Manual rework use heuristic assumptions.",
        "Schedule and source rows are analyst inputs; defaults are daily and 1,000 rows.",
        "Optimized assumes staggered runs; Peak assumes concurrent starts in the burst window.",
        (
            "Autoscale Billing for Spark offloads Notebook CU demand from the base F-SKU."
            if settings.spark_billing_mode == "autoscale"
            else "Capacity-billed Spark includes Notebook CU demand inside the base F-SKU."
        ),
        "Storage, network egress, and Fabric pricing remain excluded.",
    ]
    return CapacityPortfolioEstimate(
        status=status,
        settings=settings,
        workflow_count=workflow_count,
        eligible_count=eligible_count,
        modeled_count=modeled_count,
        excluded_count=excluded_count,
        unconfirmed_count=unconfirmed_count,
        calibrated_count=calibrated_count,
        heuristic_count=heuristic_count,
        coverage_percent=coverage,
        monthly_cu_hours=monthly_cu_hours,
        daily_cu_seconds=daily_cu_seconds,
        background_cu=background_cu,
        autoscale_spark_daily_cu_seconds=autoscale_spark_daily_cu_seconds,
        autoscale_spark_monthly_cu_hours=autoscale_spark_monthly_cu_hours,
        target_counts=target_counts,
        scenarios=scenarios,
        workflows=workflows,
        assumptions=assumptions,
    )


def capacity_csv(estimate: CapacityPortfolioEstimate) -> str:
    """Export workflow contribution and input status without spreadsheet formulas."""
    output = io.StringIO()
    writer = csv.writer(output, lineterminator="\r\n")
    writer.writerow(
        [
            "Workflow",
            "Recommended target",
            "Target components",
            "Model basis",
            "Status",
            "Exclusion reason",
            "Refresh interval minutes",
            "Source rows per run",
            "Spark vCores",
            "Notebook runtime seconds",
            "Confirmed",
            "Runs per day",
            "Complexity units",
            "Query seconds",
            "Dataflow CU-seconds",
            "Notebook CU-seconds",
            "Pipeline CU-seconds",
            "CU-seconds per run",
            "Monthly CU-hours",
            "Autoscale Spark monthly CU-hours",
        ]
    )
    for item in estimate.workflows:
        writer.writerow(
            [
                _defuse(item.workflow_path),
                _defuse(item.recommended_target),
                _defuse(", ".join(item.target_components)),
                item.model_basis or "",
                item.status,
                _defuse(item.exclusion_reason or ""),
                item.refresh_interval_minutes,
                item.source_rows_per_run,
                item.spark_vcores,
                item.effective_notebook_runtime_seconds or "",
                item.confirmed,
                item.runs_per_day or "",
                item.complexity_units or "",
                item.query_seconds or "",
                item.dataflow_cu_seconds_per_run or "",
                item.notebook_cu_seconds_per_run or "",
                item.pipeline_cu_seconds_per_run or "",
                item.projected_cu_seconds_per_run or "",
                item.monthly_cu_hours or "",
                item.autoscale_spark_monthly_cu_hours or "",
            ]
        )
    return output.getvalue()


def _estimate_workflow(
    path: str,
    recommended_target: str,
    components: list[str],
    profile: CapacityStaticProfile,
    input_value: CapacityWorkflowInput,
    settings: CapacitySettings,
) -> CapacityWorkflowEstimate:
    runs_per_day = 1440 / input_value.refresh_interval_minutes
    active_weights = (
        INFORMATICA_WEIGHTS if profile.profile_kind == "informatica" else WEIGHTS
    )
    active_keys = (
        INFORMATICA_COUNT_KEYS if profile.profile_kind == "informatica" else COUNT_KEYS
    )
    complexity = sum(profile.counts[key] * active_weights[key] for key in active_keys)
    has_dataflow = "Dataflow Gen2" in components
    has_notebook = "Fabric Notebook" in components
    has_pipeline = "Fabric Pipeline" in components
    model_basis: Literal["calibrated", "heuristic"] = (
        "calibrated"
        if recommended_target == "Dataflow Gen2" and components == ["Dataflow Gen2"]
        else "heuristic"
    )

    duration_driver: Literal["minimum", "complexity", "row_volume"] | None = None
    row_volume_threshold: int | None = None
    query_seconds: float | None = None
    dataflow_cu_seconds = 0.0
    if has_dataflow:
        complexity_seconds = complexity * settings.seconds_per_complexity_element
        volume_seconds = (
            input_value.source_rows_per_run / 100 * settings.seconds_per_hundred_rows
        )
        base_seconds = max(
            settings.minimum_seconds_per_output,
            complexity_seconds,
            volume_seconds,
        )
        if base_seconds == volume_seconds:
            duration_driver = "row_volume"
        elif base_seconds == complexity_seconds:
            duration_driver = "complexity"
        else:
            duration_driver = "minimum"
        row_volume_threshold = (
            round(
                max(settings.minimum_seconds_per_output, complexity_seconds)
                * 100
                / settings.seconds_per_hundred_rows
            )
            if settings.seconds_per_hundred_rows
            else None
        )
        query_seconds = base_seconds + (
            input_value.source_rows_per_run
            / 1000
            * profile.heavy_steps
            * settings.seconds_per_heavy_step_per_thousand_rows
        )
        outputs = max(profile.counts["dest"], 1)
        overlap = 1 + (outputs - 1) * settings.extra_output_overlap
        dataflow_cu_seconds = (
            overlap
            * (
                min(query_seconds, settings.cu_rate_threshold_seconds)
                * settings.initial_cu_rate
                + max(query_seconds - settings.cu_rate_threshold_seconds, 0)
                * settings.subsequent_cu_rate
            )
            * settings.calibration_multiplier
        )

    notebook_cu_seconds = 0.0
    effective_notebook_runtime: float | None = None
    if has_notebook:
        spark_cu = input_value.spark_vcores / 2.0
        if input_value.notebook_runtime_seconds is not None:
            effective_notebook_runtime = float(input_value.notebook_runtime_seconds)
        else:
            nb_weight = (
                max(
                    1.0,
                    profile.notebook_steps * 1.5
                    + max(profile.total_steps - profile.notebook_steps, 0) * 0.15,
                )
                if has_dataflow
                else max(1.0, complexity)
            )
            effective_notebook_runtime = max(
                60.0,
                45.0
                + nb_weight * 4.0
                + input_value.source_rows_per_run / 50_000 * 5.0
                + profile.heavy_steps * input_value.source_rows_per_run / 1_000 * 0.5,
            )
        notebook_cu_seconds = spark_cu * effective_notebook_runtime

    pipeline_cu_seconds = 0.0
    if has_pipeline:
        orchestrated_children = (1 if has_dataflow else 0) + (1 if has_notebook else 0)
        activity_count = max(orchestrated_children, 1) + profile.pipeline_steps
        orchestration_cu = (
            activity_count * settings.pipeline_orchestration_cu_seconds_per_activity
        )
        has_copy = profile.pipeline_steps > 0 or not (has_dataflow or has_notebook)
        copy_seconds = (
            settings.pipeline_copy_base_seconds
            + input_value.source_rows_per_run / 100_000 * 10.0
            if has_copy
            else 0.0
        )
        pipeline_cu_seconds = orchestration_cu + copy_seconds * settings.pipeline_copy_cu_per_second

    if settings.spark_billing_mode == "autoscale":
        cu_seconds = dataflow_cu_seconds + pipeline_cu_seconds
        autoscale_cu_seconds = notebook_cu_seconds * (1 + settings.projection_variation)
    else:
        cu_seconds = dataflow_cu_seconds + notebook_cu_seconds + pipeline_cu_seconds
        autoscale_cu_seconds = 0.0
    projected = cu_seconds * (1 + settings.projection_variation)
    monthly = projected * runs_per_day * settings.days_per_month / 3600
    autoscale_monthly = autoscale_cu_seconds * runs_per_day * settings.days_per_month / 3600
    return CapacityWorkflowEstimate(
        workflow_path=path,
        recommended_target=recommended_target,
        target_components=components,
        model_basis=model_basis,
        status="estimated" if input_value.confirmed else "unconfirmed",
        refresh_interval_minutes=input_value.refresh_interval_minutes,
        source_rows_per_run=input_value.source_rows_per_run,
        spark_vcores=input_value.spark_vcores,
        notebook_runtime_seconds=input_value.notebook_runtime_seconds,
        effective_notebook_runtime_seconds=effective_notebook_runtime,
        confirmed=input_value.confirmed,
        runs_per_day=runs_per_day,
        complexity_units=complexity,
        heavy_steps=profile.heavy_steps,
        duration_driver=duration_driver,
        row_volume_threshold=row_volume_threshold,
        query_seconds=query_seconds,
        dataflow_cu_seconds_per_run=dataflow_cu_seconds,
        notebook_cu_seconds_per_run=notebook_cu_seconds,
        pipeline_cu_seconds_per_run=pipeline_cu_seconds,
        cu_seconds_per_run=cu_seconds,
        projected_cu_seconds_per_run=projected,
        monthly_cu_hours=monthly,
        autoscale_spark_monthly_cu_hours=autoscale_monthly,
    )


def _effective_components(assessment: CapacityAssessment) -> list[str]:
    configured = [
        component
        for component in assessment.target_components
        if component in FABRIC_COMPONENTS
    ]
    if configured:
        return configured
    if assessment.recommended_target in FABRIC_COMPONENTS:
        return [assessment.recommended_target]
    if assessment.recommended_target == "Mixed Fabric solution":
        return list(FABRIC_COMPONENTS)
    if assessment.recommended_target == "Manual rework":
        return ["Dataflow Gen2"]
    return []


def _capacity_exclusion(
    assessment: CapacityAssessment,
    profile: object,
    components: list[str],
) -> str | None:
    if assessment.source_platform not in SUPPORTED_PLATFORMS:
        return "Source platform is not supported by the capacity model."
    if assessment.recommended_target not in ELIGIBLE_TARGETS or not components:
        return (
            "Capacity model supports Dataflow Gen2, Notebook, Pipeline, "
            "Mixed, and Manual rework routes."
        )
    if not isinstance(profile, CapacityStaticProfile):
        return "Static capacity profile is unavailable."
    if profile.covered_by_linked_mapping:
        return "Mapping task is covered by its referenced mapping and taskflow."
    return None


def _scenario(
    name: Literal["Optimized", "Balance", "Peak"],
    required_cu: float,
) -> CapacityScenario:
    return CapacityScenario(
        name=name,
        required_cu=required_cu,
        recommended_sku=_sku(required_cu),
    )


def _sku(required_cu: float) -> str:
    if required_cu <= 0:
        return "No demand"
    for tier in SKU_TIERS:
        if required_cu <= tier:
            return f"F{tier}"
    return "Multiple capacities (>F8192)"


def _classify_node(node: GraphNode) -> str:
    token = _token(node)
    macro = node.macro
    config = " ".join(node.configuration.values())
    if macro:
        blob = f"{macro} {config}".casefold()
        if re.search(
            r"spatial|tradearea|distance|buffer|greatarc|findnearest|latitude|longitude",
            blob,
        ):
            return "spatial"
        if re.search(r"python|predictive|alteryxr|\.r\b", blob):
            return "predictive"
        return "macro"
    if not token:
        return "skip"
    if re.search(r"toolcontainer|controlcontainer|textbox|comment|explorerbox|browse", token):
        return "skip"
    exact = {
        "directory": "folder",
        "textinput": "source",
        "dbfileinput": "source",
        "dynamicinput": "source",
        "inputdata": "source",
        "dbfileoutput": "dest",
        "outputdata": "dest",
        "render": "report",
        "reportmap": "report",
        "alteryxselect": "select",
        "select": "select",
        "filter": "filter",
        "joinmultiple": "merge3",
        "findreplace": "find",
        "appendfields": "merge",
        "join": "merge",
        "union": "append",
        "summarize": "group",
        "sort": "sort",
        "unique": "unique",
        "sample": "sample",
        "randomsample": "sample",
        "crosstab": "pivot",
        "transpose": "unpivot",
        "arrange": "arrange",
        "download": "api",
        "jsonparse": "heavy",
        "fuzzymatch": "heavy",
        "generaterows": "heavy",
        "formula": "calc",
        "multirowformula": "calc",
        "multifieldformula": "calc",
        "datetime": "calc",
    }
    if token in exact:
        return exact[token]
    if "input" in token and "output" not in token:
        return "source"
    if "output" in token:
        return "dest"
    if "clean" in token:
        return "clean"
    if re.search(r"spatial|tradearea|distance|buffer|findnearest|createpoints", token):
        return "spatial"
    if re.search(r"predictive|python|alteryxr", token):
        return "predictive"
    if "macro" in token:
        return "macro"
    if token == "regex":
        method = _configuration_text(node, "Method").casefold()
        return "clean" if "replace" in method else "calc"
    return "other"


def _token(node: GraphNode) -> str:
    if node.plugin.casefold().endswith(".dll") and node.engine_entry:
        return node.engine_entry.casefold()
    plugin_token = node.plugin.rsplit(".", 1)[-1].casefold()
    return plugin_token or node.engine_entry.casefold()


def _database_key(node: GraphNode) -> str:
    file_text = _configuration_text(node, "File").strip()
    blob = f"{file_text} {' '.join(node.configuration.values())}".casefold()
    if not blob:
        return ""
    if re.search(r"\.(xlsx|xls|xlsb|csv|txt|yxdb|xml|json|avro|parquet|tsv)(?:\||\s|$)", file_text):
        return ""
    if re.match(r"^(?:\\\\|[a-z]:\\|\.{0,2}[\\/])", file_text, re.IGNORECASE):
        return ""
    if not re.search(
        r"aka:|odbc:|oledb:|jdbc:|sqlserver|oracle|snowflake|databricks|postgres|"
        r"mysql|teradata|bigquery|server\s*=|dsn\s*=|database\s*=",
        blob,
    ):
        return ""
    alias = re.search(r"\baka:([^|;<\s]+)", blob)
    dsn = re.search(r"\bdsn\s*=\s*([^;<|]+)", blob)
    server = re.search(r"\b(?:server|host|data source)\s*=\s*([^;<|]+)", blob)
    database = re.search(r"\b(?:database|initial catalog)\s*=\s*([^;<|]+)", blob)
    provider = re.search(
        r"\b(sqlserver|oracle|snowflake|databricks|postgres|mysql|teradata|"
        r"bigquery|odbc|oledb|jdbc)\b",
        blob,
    )
    if alias:
        return f"aka:{alias.group(1)}"
    if dsn:
        return f"dsn:{dsn.group(1).strip()}"
    if server or database:
        return f"db:{server.group(1).strip() if server else ''}/" + (
            database.group(1).strip() if database else ""
        )
    return f"provider:{provider.group(1)}" if provider else ""


def _configuration_text(node: GraphNode, key: str) -> str:
    xml = node.configuration.get(key, "")
    if not xml:
        return ""
    try:
        root = SafeElementTree.fromstring(
            xml,
            forbid_dtd=True,
            forbid_entities=True,
            forbid_external=True,
        )
    except (SafeElementTree.ParseError, DefusedXmlException):
        return ""
    return "".join(root.itertext()).strip()


def _defuse(value: str) -> str:
    return f"'{value}" if re.match(r"^\s*[=+\-@]", value) else value


def _informatica_db_key(value: str) -> str:
    text = value.strip()
    if text.startswith("$"):
        text = text[1:]
    text = text.casefold()
    if not text or text in {"source", "target"}:
        return ""
    return text


def _tally_informatica_bucket(counts: dict[str, int], bucket: str) -> tuple[int, int]:
    notebook_delta = 1 if bucket in {"code", "api"} else 0
    if bucket in {"xmlsource", "xmlfolder"}:
        counts["source" if bucket == "xmlsource" else "folder"] += 1
        return 1, notebook_delta
    if bucket == "heavy":
        return 1, notebook_delta
    counts[bucket] += 1
    return 0, notebook_delta


def _classify_informatica_node(node: EtlNode, *, is_idmc: bool) -> str:
    raw_template = node.properties.get("template_name")
    template = raw_template.casefold() if isinstance(raw_template, str) else ""
    raw_groups = node.properties.get("port_groups")
    groups: set[str] = set()
    if isinstance(raw_groups, dict):
        input_names = {
            port.name for port in node.ports if port.direction in {"input", "input_output"}
        }
        for port_name, group_name in raw_groups.items():
            if (not input_names or port_name in input_names) and isinstance(group_name, str):
                groups.add(group_name)
    return _classify_informatica_operation(
        node.operation.casefold(),
        template,
        len(groups) or 2,
        is_idmc=is_idmc,
    )


def _classify_informatica_operation(
    operation: str,
    template: str,
    input_group_count: int,
    *,
    is_idmc: bool,
) -> str:
    if operation in {
        "source_definition",
        "input_transformation",
        "output_transformation",
        "transaction_control",
        "start",
        "decision",
        "assignment",
        "annotation",
        "container",
        "end",
    }:
        return "skip"
    if operation == "source":
        return "source" if is_idmc else "skip"
    if operation in {"target_definition", "target"}:
        return "dest"
    if operation in {"source_qualifier", "application_source_qualifier"}:
        return "source"
    if operation == "xml_source_qualifier":
        return "xmlsource"
    if operation in {"filter", "router"}:
        return "filter"
    if operation in {"expression", "sequence_generator", "sequence"}:
        return "calc"
    if operation == "joiner":
        return "merge3" if input_group_count >= 3 else "merge"
    if operation in {"lookup_procedure", "lookup"}:
        return "lookup"
    if operation == "aggregator":
        return "group"
    if operation == "sorter":
        return "sort"
    if operation in {"normalizer", "union_transformation", "union"}:
        return "reshape"
    if operation == "update_strategy":
        return "update"
    if operation in {"stored_procedure", "java", "sql"}:
        return "code"
    if operation in {"http", "web_service", "web_services", "rest"}:
        return "api"
    if operation in {"xml_parser", "json", "unstructured", "hierarchy_parser", "structure_parser"}:
        return "heavy"
    if operation == "rank":
        return "other"
    if operation == "mapplet":
        return "skip"
    if operation == "custom_transformation":
        if "union" in template:
            return "reshape"
        if re.search(r"sql|java|stored|procedure", template):
            return "code"
        if re.search(r"http|web service|rest", template):
            return "api"
        if re.search(r"xml parser|json|unstructured", template):
            return "heavy"
        return "other"
    return "other" if operation else "skip"
