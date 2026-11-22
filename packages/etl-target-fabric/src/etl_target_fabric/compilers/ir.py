"""Bounded Informatica-to-Fabric compiler over canonical ETL IR."""

from __future__ import annotations

import json
import re
from dataclasses import dataclass
from typing import Literal

from etl_migration_core.contracts.ir import (
    EXTENSIBLE_SOURCE_IR_VERSION,
    IR_VERSION,
    AssetType,
    EtlAsset,
    EtlEdge,
    EtlGraph,
    EtlNode,
    EtlPackage,
    GraphKind,
    NodeKind,
    SourcePlatform,
)
from etl_migration_core.m_literals import m_string, m_text_is_well_formed

CompilationTarget = Literal["dataflow", "notebook", "pipeline"]
ETL_COMPILER_VERSION = "1.4.1"
SUPPORTED_IR_VERSIONS = (IR_VERSION, EXTENSIBLE_SOURCE_IR_VERSION)
SUPPORTED_MAPPING_OPERATIONS = frozenset(
    {
        "source",
        "source_qualifier",
        "xml_source_qualifier",
        "filter",
        "expression",
        "router",
        "aggregator",
        "custom_transformation",
        "target",
    }
)


@dataclass(frozen=True, slots=True)
class EtlCompiledCandidate:
    """Generated code or explicit scaffold for one canonical asset."""

    asset_id: str
    name: str
    target: CompilationTarget
    validation_state: Literal["generated_unvalidated", "scaffold"]
    deployable: bool
    runtime_ready: bool
    code: str
    diagnostics: tuple[str, ...] = ()
    required_bindings: tuple[str, ...] = ()
    definition_queries: tuple[str, ...] = ()
    loaded_outputs: tuple[str, ...] = ()


@dataclass(frozen=True, slots=True)
class EtlCompiledTargets:
    """Compiler results reused for routing across every supported target."""

    dataflow: EtlCompiledCandidate
    notebook: EtlCompiledCandidate
    pipeline: EtlCompiledCandidate

    def values(self) -> tuple[EtlCompiledCandidate, ...]:
        return (self.dataflow, self.notebook, self.pipeline)


def compile_asset(
    package: EtlPackage,
    asset: EtlAsset,
    target: CompilationTarget,
) -> EtlCompiledCandidate:
    """Compile one normalized asset to a bounded Fabric target."""
    if package.ir_version not in SUPPORTED_IR_VERSIONS:
        raise ValueError(f"Fabric compiler does not support IR version {package.ir_version!r}")
    if not isinstance(package.source_platform, SourcePlatform):
        raise ValueError(f"Fabric compiler does not support source {package.source_platform!r}")
    if target == "pipeline":
        dataflow = compile_asset(package, asset, "dataflow")
        notebook = (
            compile_asset(package, asset, "notebook")
            if len(asset.mapping_graphs) > 1 and not dataflow.deployable
            else None
        )
        return _compile_pipeline_candidate(asset, dataflow, notebook)
    if not asset.mapping_graphs:
        return _scaffold(
            asset,
            target,
            "Exactly one mapping graph is required for this compiler subset",
        )
    if len(asset.mapping_graphs) > 1:
        return _fail_closed_m(_compile_multi_mapping(package, asset, target))
    return _fail_closed_m(_compile_mapping(package, asset, asset.mapping_graphs[0], target))


def compile_asset_targets(
    package: EtlPackage,
    asset: EtlAsset,
) -> EtlCompiledTargets:
    """Compile each target once so routing can reuse dependency analysis."""
    dataflow = compile_asset(package, asset, "dataflow")
    notebook = compile_asset(package, asset, "notebook")
    return EtlCompiledTargets(
        dataflow=dataflow,
        notebook=notebook,
        pipeline=_compile_pipeline_candidate(asset, dataflow, notebook),
    )


def _compile_pipeline_candidate(
    asset: EtlAsset,
    dataflow: EtlCompiledCandidate,
    notebook: EtlCompiledCandidate | None,
) -> EtlCompiledCandidate:
    compute_target: Literal["dataflow", "notebook"] = "dataflow"
    if len(asset.mapping_graphs) == 1 and not dataflow.deployable:
        detail = dataflow.diagnostics[0] if dataflow.diagnostics else "unknown"
        return _scaffold(
            asset,
            "pipeline",
            f"Pipeline dependency is not deployable: {detail}",
        )
    if len(asset.mapping_graphs) > 1 and not dataflow.deployable:
        if notebook is None or not notebook.deployable:
            detail = (
                notebook.diagnostics[0]
                if notebook is not None and notebook.diagnostics
                else "unknown"
            )
            return _scaffold(
                asset,
                "pipeline",
                f"Pipeline dependencies are not deployable: {detail}",
            )
        compute_target = "notebook"
    return _compile_pipeline(asset, compute_target=compute_target)


@dataclass(frozen=True, slots=True)
class _CompiledMappingFragment:
    target: Literal["dataflow", "notebook"]
    lines: list[str]
    definition_queries: list[str]
    source_bindings: list[str]
    transform_bindings: list[str]
    destination_bindings: list[str]
    outputs: list[str]
    uses_sql_transforms: bool


def _compile_multi_mapping(
    package: EtlPackage,
    asset: EtlAsset,
    target: Literal["dataflow", "notebook"],
) -> EtlCompiledCandidate:
    sessions = _ordered_session_mappings(asset)
    if sessions is None:
        return _scaffold(asset, target, "Orchestration graph contains a cycle")
    if target == "dataflow":
        fragments: list[tuple[str, _CompiledMappingFragment]] = []
        failures: list[str] = []
        for _session_node, session_name, mapping_name, graph in sessions:
            var_prefix = _safe_identifier(session_name)
            result = _compile_mapping_fragment(
                asset,
                graph,
                "dataflow",
                key_prefix=mapping_name,
                var_prefix=var_prefix,
            )
            if isinstance(result, EtlCompiledCandidate):
                detail = result.diagnostics[0] if result.diagnostics else "unsupported"
                failures.append(f"{mapping_name}: {detail}")
            else:
                fragments.append((mapping_name, result))
        if failures:
            return _scaffold(asset, "dataflow", "; ".join(failures[:4]))
        lines = [
            "section Section1;",
            "",
            'shared SourceBindings = error "Configure source bindings before refresh";',
        ]
        definition_queries = ["SourceBindings"]
        if any(fragment.uses_sql_transforms for _, fragment in fragments):
            lines.extend(
                [
                    "",
                    (
                        'shared SqlTransformBindings = error "Configure SQL '
                        'transform functions before refresh";'
                    ),
                ]
            )
            definition_queries.append("SqlTransformBindings")
        source_bindings: list[str] = []
        transform_bindings: list[str] = []
        destination_bindings: list[str] = []
        outputs: list[str] = []
        for _, fragment in fragments:
            lines.extend(fragment.lines)
            definition_queries.extend(fragment.definition_queries)
            source_bindings.extend(fragment.source_bindings)
            transform_bindings.extend(fragment.transform_bindings)
            destination_bindings.extend(fragment.destination_bindings)
            outputs.extend(fragment.outputs)
        return EtlCompiledCandidate(
            asset_id=asset.native_id,
            name=asset.name,
            target="dataflow",
            validation_state="generated_unvalidated",
            deployable=True,
            runtime_ready=False,
            code="\n".join(lines) + "\n",
            required_bindings=tuple(
                dict.fromkeys(
                    [
                        *source_bindings,
                        *transform_bindings,
                        *destination_bindings,
                        "independent semantic parity",
                    ]
                )
            ),
            definition_queries=tuple(definition_queries),
            loaded_outputs=tuple(outputs),
        )

    statements = [
        "from pyspark.sql import functions as F",
        "",
        "source_paths = globals().get('source_paths', {})",
        "transform_bindings = globals().get('transform_bindings', {})",
        "workflow_vars = dict(globals().get('workflow_vars', {}))",
        "",
        "def require_transform(name):",
        "    binding = transform_bindings.get(name)",
        "    if binding is None:",
        '        raise ValueError(f"Configure transform_bindings[{name!r}] before running")',
        "    return binding",
        "",
        "def _read_source(location):",
        '    if location.endswith(".parquet") or "/parquet/" in location.lower():',
        "        return spark.read.parquet(location)",
        '    if "/" not in location and "\\\\" not in location and not location.endswith(".csv"):',
        "        return spark.read.table(location)",
        '    return spark.read.option("header", True).option("inferSchema", True).csv(location)',
    ]
    consolidate_sessions = _consolidates_compute_sessions(asset)
    if not consolidate_sessions:
        statements.append("selected_session = str(globals().get('session', '') or '')")
    if asset.orchestration_graph is not None:
        ordered_tasks = _topological_nodes(asset.orchestration_graph)
        if ordered_tasks is None:
            return _scaffold(asset, "notebook", "Orchestration graph contains a cycle")
        for task in ordered_tasks:
            if task.operation != "assignment":
                continue
            raw_assignments = task.properties.get("assignments")
            if not isinstance(raw_assignments, list):
                continue
            for pair in raw_assignments:
                if isinstance(pair, dict) and pair.get("name"):
                    var_name = str(pair["name"])
                    raw_value = str(pair.get("value", ""))
                    var_value = "" if raw_value == "''" else raw_value
                    param_key = var_name.lstrip("$")
                    if param_key:
                        statements.append(
                            f"{param_key} = globals().get({param_key!r}, {var_value!r})"
                        )
                        statements.append(
                            f"workflow_vars.setdefault({var_name!r}, {param_key})"
                        )
                    else:
                        statements.append(
                            f"workflow_vars.setdefault({var_name!r}, {var_value!r})"
                        )

    source_bindings = []
    transform_bindings = []
    outputs = []
    runners: list[tuple[str, str]] = []
    used_runner_names: set[str] = set()
    for session_node, session_name, mapping_name, graph in sessions:
        var_prefix = _safe_identifier(session_name)
        fragment_result = _compile_mapping_fragment(
            asset,
            graph,
            "notebook",
            key_prefix=mapping_name,
            var_prefix=var_prefix,
        )
        if isinstance(fragment_result, EtlCompiledCandidate):
            return fragment_result
        body_lines: list[str] = []
        if session_node is not None:
            pre_assignments = session_node.properties.get("pre_assignments")
            if isinstance(pre_assignments, list):
                for pair in pre_assignments:
                    if isinstance(pair, dict) and pair.get("name"):
                        body_lines.append(
                            f"workflow_vars[{str(pair['name'])!r}] = "
                            f"workflow_vars.get({str(pair.get('value', ''))!r}, "
                            f"{str(pair.get('value', ''))!r})"
                        )
        body_lines.extend(fragment_result.lines)
        body_lines.extend(f"display({output})" for output in fragment_result.outputs)
        if session_node is not None:
            post_assignments = session_node.properties.get("post_assignments")
            if isinstance(post_assignments, list):
                for pair in post_assignments:
                    if isinstance(pair, dict) and pair.get("name"):
                        body_lines.append(
                            f"workflow_vars[{str(pair['name'])!r}] = "
                            f"workflow_vars.get({str(pair.get('value', ''))!r}, "
                            f"{str(pair.get('value', ''))!r})"
                        )
        if consolidate_sessions:
            statements.extend(["", *body_lines])
        else:
            runner_name = f"_run_{var_prefix}"
            if runner_name in used_runner_names:
                runner_name = f"{runner_name}_{len(used_runner_names) + 1}"
            used_runner_names.add(runner_name)
            runners.append((session_name, runner_name))
            if not body_lines:
                body_lines.append("pass")
            statements.extend(["", f"def {runner_name}():"])
            statements.extend(f"    {line}" if line else "" for line in body_lines)
        source_bindings.extend(fragment_result.source_bindings)
        transform_bindings.extend(fragment_result.transform_bindings)
        outputs.extend(fragment_result.outputs)

    if not consolidate_sessions:
        statements.extend(
            [
                "",
                "for _session_name, _runner in [",
                *[
                    f"    ({session_name!r}, {runner_name}),"
                    for session_name, runner_name in runners
                ],
                "]:",
                "    if not selected_session or selected_session == _session_name:",
                "        _runner()",
            ]
        )
    return EtlCompiledCandidate(
        asset_id=asset.native_id,
        name=asset.name,
        target="notebook",
        validation_state="generated_unvalidated",
        deployable=True,
        runtime_ready=False,
        code="\n".join(statements) + "\n",
        required_bindings=tuple(
            dict.fromkeys(
                [*source_bindings, *transform_bindings, "independent semantic parity"]
            )
        ),
        loaded_outputs=tuple(outputs),
    )


def _compile_mapping(
    package: EtlPackage,
    asset: EtlAsset,
    graph: EtlGraph,
    target: Literal["dataflow", "notebook"],
) -> EtlCompiledCandidate:
    result = _compile_mapping_fragment(asset, graph, target)
    if isinstance(result, EtlCompiledCandidate):
        return result
    if target == "dataflow":
        lines = [
            "section Section1;",
            "",
            'shared SourceBindings = error "Configure source bindings before refresh";',
        ]
        definition_queries = ["SourceBindings"]
        if result.uses_sql_transforms:
            lines.extend(
                [
                    "",
                    (
                        'shared SqlTransformBindings = error "Configure SQL '
                        'transform functions before refresh";'
                    ),
                ]
            )
            definition_queries.append("SqlTransformBindings")
        lines.extend(result.lines)
        definition_queries.extend(result.definition_queries)
        return EtlCompiledCandidate(
            asset_id=asset.native_id,
            name=asset.name,
            target=target,
            validation_state="generated_unvalidated",
            deployable=True,
            runtime_ready=False,
            code="\n".join(lines) + "\n",
            required_bindings=tuple(
                [
                    *result.source_bindings,
                    *result.transform_bindings,
                    *result.destination_bindings,
                    "independent semantic parity",
                ]
            ),
            definition_queries=tuple(definition_queries),
            loaded_outputs=tuple(result.outputs),
        )

    statements = [
        "from pyspark.sql import functions as F",
        "",
        "source_paths = globals().get('source_paths', {})",
        "transform_bindings = globals().get('transform_bindings', {})",
        "",
        "def require_transform(name):",
        "    binding = transform_bindings.get(name)",
        "    if binding is None:",
        '        raise ValueError(f"Configure transform_bindings[{name!r}] before running")',
        "    return binding",
        "",
        "def _read_source(location):",
        '    if location.endswith(".parquet") or "/parquet/" in location.lower():',
        "        return spark.read.parquet(location)",
        '    if "/" not in location and "\\\\" not in location and not location.endswith(".csv"):',
        "        return spark.read.table(location)",
        '    return spark.read.option("header", True).option("inferSchema", True).csv(location)',
        *result.lines,
        "",
        *[f"display({output})" for output in result.outputs],
    ]
    return EtlCompiledCandidate(
        asset_id=asset.native_id,
        name=asset.name,
        target=target,
        validation_state="generated_unvalidated",
        deployable=True,
        runtime_ready=False,
        code="\n".join(statements) + "\n",
        required_bindings=tuple(
            [
                *result.source_bindings,
                *result.transform_bindings,
                "independent semantic parity",
            ]
        ),
        loaded_outputs=tuple(result.outputs),
    )


def _compile_mapping_fragment(
    asset: EtlAsset,
    graph: EtlGraph,
    target: Literal["dataflow", "notebook"],
    *,
    key_prefix: str | None = None,
    var_prefix: str | None = None,
) -> _CompiledMappingFragment | EtlCompiledCandidate:
    if graph.kind is not GraphKind.MAPPING:
        return _scaffold(asset, target, "A mapping graph is required")
    ordered = _topological_nodes(graph)
    if ordered is None:
        return _scaffold(asset, target, "Mapping graph contains a cycle")
    unsupported = sorted(
        {
            node.operation
            for node in ordered
            if node.operation not in SUPPORTED_MAPPING_OPERATIONS
        }
    )
    if target == "dataflow" and unsupported:
        return _scaffold(
            asset,
            target,
            f"Unsupported operations: {', '.join(unsupported)}",
        )

    incoming: dict[str, list[EtlEdge]] = {node.native_id: [] for node in ordered}
    for edge in graph.edges:
        incoming[edge.target].append(edge)
    by_id = {node.native_id: node for node in ordered}
    names = _query_names(ordered, prefix=var_prefix)
    if target == "dataflow":
        return _compile_dataflow_mapping(
            asset,
            ordered,
            incoming,
            by_id,
            names,
            key_prefix=key_prefix,
        )

    route_names: dict[tuple[str, str], str] = {}
    source_bindings: list[str] = []
    transform_bindings: list[str] = []
    outputs: list[str] = []
    statements: list[str] = []
    for node in ordered:
        name = names[node.native_id]
        binding_key = (
            f"{key_prefix}/{node.native_id}" if key_prefix else node.native_id
        )
        sources = _incoming_query_names(
            node.native_id,
            incoming,
            by_id,
            names,
            route_names,
        )
        if sources is None:
            return _scaffold(
                asset,
                target,
                f"Unsupported {node.operation} output routing",
            )
        if node.operation == "router":
            notebook_routes = _notebook_router_statements(
                node, name, sources, binding_key=binding_key
            )
            if notebook_routes is None:
                return _scaffold(
                    asset,
                    target,
                    "Unsupported router configuration",
                )
            route_statements, route_outputs = notebook_routes
            statements.extend(route_statements)
            for group, query_name in route_outputs:
                route_names[(node.native_id, group)] = query_name
            transform_bindings.append(
                f"transform_bindings[{binding_key!r}] (router)"
            )
            continue
        generated_statements = _notebook_statements(
            node, name, sources, binding_key=binding_key
        )
        if generated_statements is None:
            arguments = ", ".join(sources)
            generated_statements = [
                f"{name} = require_transform({json.dumps(binding_key)})({arguments})"
            ]
            transform_bindings.append(
                f"transform_bindings[{binding_key!r}] ({node.operation})"
            )
        statements.extend(generated_statements)
        if node.kind is NodeKind.SOURCE:
            source_bindings.append(f"source_paths[{binding_key!r}]")
        if node.kind is NodeKind.TARGET:
            outputs.append(name)
    return _CompiledMappingFragment(
        target=target,
        lines=statements,
        definition_queries=[],
        source_bindings=source_bindings,
        transform_bindings=transform_bindings,
        destination_bindings=[],
        outputs=outputs,
        uses_sql_transforms=False,
    )


def _consolidates_compute_sessions(asset: EtlAsset) -> bool:
    if len(asset.mapping_graphs) <= 1 or asset.orchestration_graph is None:
        return True
    ordered = _topological_nodes(asset.orchestration_graph)
    if ordered is None:
        return False
    task_nodes = [
        node
        for node in ordered
        if node.kind not in {NodeKind.CONTROL, NodeKind.ANNOTATION}
    ]
    session_operations = {"mapping_task", "mappingtask", "session"}
    session_indices = [
        index
        for index, node in enumerate(task_nodes)
        if node.operation in session_operations
    ]
    return (
        len(session_indices) > 1
        and session_indices == list(range(session_indices[0], session_indices[-1] + 1))
        and session_indices[-1] == len(task_nodes) - 1
    )


def _compile_pipeline(
    asset: EtlAsset,
    *,
    compute_target: Literal["dataflow", "notebook"] = "dataflow",
) -> EtlCompiledCandidate:
    graph = asset.orchestration_graph
    if graph is None or graph.kind is not GraphKind.ORCHESTRATION:
        return _scaffold(asset, "pipeline", "An orchestration graph is required")
    ordered = _topological_nodes(graph)
    if ordered is None:
        return _scaffold(asset, "pipeline", "Orchestration graph contains a cycle")
    task_nodes = [
        node
        for node in ordered
        if node.kind not in {NodeKind.CONTROL, NodeKind.ANNOTATION}
    ]
    if (
        asset.asset_type is AssetType.WORKFLOW
        and len(asset.mapping_graphs) == 1
        and len(task_nodes) == 1
        and task_nodes[0].operation == "session"
    ):
        return _scaffold(
            asset,
            "pipeline",
            "A single PowerCenter session deploys directly as Dataflow Gen2; "
            "a Fabric Pipeline is not required",
        )
    if not task_nodes:
        return _scaffold(
            asset,
            "pipeline",
            "At least one mapping task or session is required for this compiler subset",
        )
    supported = {"mapping_task", "mappingtask", "session", "assignment"}
    unsupported = sorted(
        {node.operation for node in task_nodes if node.operation not in supported}
    )
    if unsupported:
        return _scaffold(
            asset,
            "pipeline",
            f"Unsupported orchestration operations: {', '.join(unsupported)}",
        )

    predecessors: dict[str, list[str]] = {node.native_id: [] for node in ordered}
    for edge in graph.edges:
        predecessors[edge.target].append(edge.source)
    terminal_activities: dict[str, list[str]] = {}
    for node in ordered:
        if node.kind in {NodeKind.CONTROL, NodeKind.ANNOTATION}:
            inherited: list[str] = []
            for pred in predecessors[node.native_id]:
                inherited.extend(terminal_activities.get(pred, []))
            terminal_activities[node.native_id] = list(dict.fromkeys(inherited))
            continue
        terminal_activities[node.native_id] = [node.name]

    activities: list[dict[str, object]] = []
    pipeline_variables: dict[str, dict[str, str]] = {}
    session_nodes: list[EtlNode] = []
    used_activity_names: set[str] = set()
    session_operations = {"mapping_task", "mappingtask", "session"}
    session_indices = [
        index
        for index, node in enumerate(task_nodes)
        if node.operation in session_operations
    ]
    consolidate_compute = (
        len(asset.mapping_graphs) > 1 and _consolidates_compute_sessions(asset)
    )
    for node in task_nodes:
        dep_activity_names: list[str] = []
        for pred in predecessors[node.native_id]:
            dep_activity_names.extend(terminal_activities.get(pred, []))
        dependencies = [
            {"activity": activity_name, "dependencyConditions": ["Succeeded"]}
            for activity_name in dict.fromkeys(dep_activity_names)
        ]
        if node.operation == "assignment":
            raw_assignments = node.properties.get("assignments")
            pairs = (
                [
                    pair
                    for pair in raw_assignments
                    if isinstance(pair, dict) and pair.get("name")
                ]
                if isinstance(raw_assignments, list)
                else []
            )
            if not pairs:
                pairs = [{"name": "workflow_initialized", "value": "true"}]
            created_names: list[str] = []
            for index, pair in enumerate(pairs, start=1):
                raw_name = str(pair["name"])
                var_name = raw_name.lstrip("$") or f"var_{index}"
                raw_val = str(pair.get("value", ""))
                clean_val = "" if raw_val == "''" else raw_val
                pipeline_variables[var_name] = {"type": "String", "defaultValue": ""}
                activity_name = (
                    node.name
                    if len(pairs) == 1 and node.name not in used_activity_names
                    else f"{node.name}_{_safe_identifier(var_name)}"
                )
                if activity_name in used_activity_names:
                    activity_name = f"{activity_name}_{index}"
                used_activity_names.add(activity_name)
                created_names.append(activity_name)
                activities.append(
                    {
                        "name": activity_name,
                        "type": "SetVariable",
                        "dependsOn": dependencies,
                        "typeProperties": {
                            "variableName": var_name,
                            "value": clean_val,
                        },
                    }
                )
            terminal_activities[node.native_id] = created_names
            continue

        session_nodes.append(node)
        if consolidate_compute:
            if node.native_id != task_nodes[session_indices[0]].native_id:
                continue
            activity_name = f"Run_{asset.name}"
            if activity_name in used_activity_names:
                activity_name = f"{activity_name}_{len(used_activity_names) + 1}"
            used_activity_names.add(activity_name)
            terminal_activities[node.native_id] = [activity_name]
            if compute_target == "notebook":
                notebook_params: dict[str, dict[str, str]] = {
                    var_name: {
                        "value": f"@variables('{var_name}')",
                        "type": "string",
                    }
                    for var_name in pipeline_variables
                }
                activities.append(
                    {
                        "name": activity_name,
                        "type": "TridentNotebook",
                        "dependsOn": dependencies,
                        "policy": {
                            "timeout": "0.12:00:00",
                            "retry": 0,
                            "retryIntervalInSeconds": 30,
                            "secureInput": False,
                            "secureOutput": False,
                        },
                        "typeProperties": {
                            "notebookId": "{{NOTEBOOK_ITEM_ID}}",
                            "parameters": notebook_params,
                            "workspaceId": "{{WORKSPACE_ID}}",
                        },
                    }
                )
            else:
                activities.append(
                    {
                        "name": activity_name,
                        "type": "RefreshDataflow",
                        "dependsOn": dependencies,
                        "policy": {
                            "timeout": "0.12:00:00",
                            "retry": 0,
                            "retryIntervalInSeconds": 30,
                            "secureInput": False,
                            "secureOutput": False,
                        },
                        "typeProperties": {
                            "dataflowId": "{{DATAFLOW_ITEM_ID}}",
                            "workspaceId": "{{WORKSPACE_ID}}",
                        },
                    }
                )
            continue

        activity_name = node.name
        if activity_name in used_activity_names:
            activity_name = f"{activity_name}_{len(used_activity_names) + 1}"
        used_activity_names.add(activity_name)
        terminal_activities[node.native_id] = [activity_name]
        if compute_target == "notebook":
            parameters: dict[str, dict[str, str]] = (
                {"session": {"value": node.name, "type": "string"}}
                if len(asset.mapping_graphs) > 1
                else {}
            )
            activities.append(
                {
                    "name": activity_name,
                    "type": "TridentNotebook",
                    "dependsOn": dependencies,
                    "policy": {
                        "timeout": "0.12:00:00",
                        "retry": 0,
                        "retryIntervalInSeconds": 30,
                        "secureInput": False,
                        "secureOutput": False,
                    },
                    "typeProperties": {
                        "notebookId": "{{NOTEBOOK_ITEM_ID}}",
                        "parameters": parameters,
                        "workspaceId": "{{WORKSPACE_ID}}",
                    },
                }
            )
        else:
            activities.append(
                {
                    "name": activity_name,
                    "type": "RefreshDataflow",
                    "dependsOn": dependencies,
                    "policy": {
                        "timeout": "0.12:00:00",
                        "retry": 0,
                        "retryIntervalInSeconds": 30,
                        "secureInput": False,
                        "secureOutput": False,
                    },
                    "typeProperties": {
                        "dataflowId": "{{DATAFLOW_ITEM_ID}}",
                        "workspaceId": "{{WORKSPACE_ID}}",
                    },
                }
            )

    properties_body: dict[str, object] = {"activities": activities}
    if pipeline_variables:
        properties_body["variables"] = pipeline_variables
    content = {"properties": properties_body}
    binding_prefix = "notebook_items" if compute_target == "notebook" else "dataflow_items"
    return EtlCompiledCandidate(
        asset_id=asset.native_id,
        name=asset.name,
        target="pipeline",
        validation_state="generated_unvalidated",
        deployable=True,
        runtime_ready=False,
        code=json.dumps(content, indent=2, sort_keys=True),
        required_bindings=(
            "workspace_id",
            *tuple(f"{binding_prefix}[{node.native_id!r}]" for node in session_nodes),
            "independent semantic parity",
        ),
    )


def _ordered_session_mappings(
    asset: EtlAsset,
) -> list[tuple[EtlNode | None, str, str, EtlGraph]] | None:
    graphs_with_names = [
        (_graph_mapping_name(graph, index), graph)
        for index, graph in enumerate(asset.mapping_graphs)
    ]
    if asset.orchestration_graph is None:
        return [
            (None, f"stage_{index + 1}", name, graph)
            for index, (name, graph) in enumerate(graphs_with_names)
        ]
    ordered = _topological_nodes(asset.orchestration_graph)
    if ordered is None:
        return None
    session_nodes = [
        node
        for node in ordered
        if node.operation in {"session", "mapping_task", "mappingtask"}
    ]
    by_name: dict[str, list[int]] = {}
    for index, (name, _graph) in enumerate(graphs_with_names):
        by_name.setdefault(name, []).append(index)
    used_indices: set[int] = set()
    result: list[tuple[EtlNode | None, str, str, EtlGraph]] = []
    for session_index, node in enumerate(session_nodes):
        mapped = node.properties.get("mapping_name")
        matched_index: int | None = None
        if isinstance(mapped, str) and mapped in by_name:
            for candidate_index in by_name[mapped]:
                if candidate_index not in used_indices:
                    matched_index = candidate_index
                    break
        if (
            matched_index is None
            and len(session_nodes) == len(graphs_with_names)
            and session_index not in used_indices
        ):
            matched_index = session_index
        if matched_index is None:
            for candidate_index in range(len(graphs_with_names)):
                if candidate_index not in used_indices:
                    matched_index = candidate_index
                    break
        if matched_index is None:
            continue
        used_indices.add(matched_index)
        mapping_name, graph = graphs_with_names[matched_index]
        result.append((node, node.name, mapping_name, graph))
    for index, (mapping_name, graph) in enumerate(graphs_with_names):
        if index not in used_indices:
            result.append((None, mapping_name, mapping_name, graph))
    return result


def _graph_mapping_name(graph: EtlGraph, index: int) -> str:
    for node in graph.nodes:
        if node.source_location and node.source_location.object_path:
            parts = node.source_location.object_path.split("/")
            if len(parts) >= 2 and parts[0] == "MAPPING" and parts[1]:
                return parts[1]
    return f"mapping_{index + 1}"


def _safe_identifier(value: str) -> str:
    cleaned = re.sub(r"[^A-Za-z0-9_]+", "_", value).strip("_").casefold()
    if not cleaned:
        return "stage"
    if cleaned[0].isdigit():
        return f"stage_{cleaned}"
    return cleaned


def _incoming_query_names(
    node_id: str,
    incoming: dict[str, list[EtlEdge]],
    by_id: dict[str, EtlNode],
    names: dict[str, str],
    route_names: dict[tuple[str, str], str],
) -> list[str] | None:
    sources: list[str] = []
    for edge in incoming[node_id]:
        source = by_id[edge.source]
        if source.operation == "router":
            groups = _string_map(source.properties.get("port_groups"))
            group = groups.get(edge.source_port or "")
            if group is None:
                return None
            query_name = route_names.get((source.native_id, group))
            if query_name is None:
                return None
        else:
            query_name = names[source.native_id]
        if query_name not in sources:
            sources.append(query_name)
    return sources


def _compile_dataflow_mapping(
    asset: EtlAsset,
    ordered: list[EtlNode],
    incoming: dict[str, list[EtlEdge]],
    by_id: dict[str, EtlNode],
    names: dict[str, str],
    *,
    key_prefix: str | None = None,
) -> _CompiledMappingFragment | EtlCompiledCandidate:
    stream_order: list[str] = []
    stream_node: dict[str, EtlNode] = {}
    stream_query_name: dict[str, str] = {}
    stream_incoming: dict[str, list[str]] = {}
    stream_outgoing: dict[str, list[str]] = {}
    route_stream_ids: dict[tuple[str, str], str] = {}
    router_plans: dict[str, tuple[str, list[tuple[str, str]], str]] = {}

    for node in ordered:
        name = names[node.native_id]
        upstream: list[str] = []
        for edge in incoming[node.native_id]:
            source = by_id[edge.source]
            if source.operation == "router":
                groups = _string_map(source.properties.get("port_groups"))
                group = groups.get(edge.source_port or "")
                if group is None:
                    return _scaffold(
                        asset, "dataflow", f"Unsupported {node.operation} output routing"
                    )
                up_id = route_stream_ids.get((source.native_id, group))
                if up_id is None:
                    return _scaffold(
                        asset, "dataflow", f"Unsupported {node.operation} output routing"
                    )
            else:
                up_id = source.native_id
            if up_id not in upstream:
                upstream.append(up_id)

        if node.operation == "router":
            if len(upstream) != 1:
                return _scaffold(asset, "dataflow", "Unsupported router configuration")
            plans = _dataflow_router_plans(node, name)
            if plans is None:
                return _scaffold(asset, "dataflow", "Unsupported router configuration")
            for group_name, route_name, aliases, condition in plans:
                sid = f"{node.native_id}::{group_name}"
                route_stream_ids[(node.native_id, group_name)] = sid
                router_plans[sid] = (route_name, aliases, condition)
                stream_order.append(sid)
                stream_node[sid] = node
                stream_query_name[sid] = route_name
                stream_incoming[sid] = list(upstream)
                stream_outgoing[sid] = []
                stream_outgoing[upstream[0]].append(sid)
            continue

        sid = node.native_id
        stream_order.append(sid)
        stream_node[sid] = node
        stream_query_name[sid] = name
        stream_incoming[sid] = upstream
        stream_outgoing[sid] = []
        for up_id in upstream:
            stream_outgoing[up_id].append(sid)

    merged_into: dict[str, str] = {}
    for sid in stream_order:
        if len(stream_outgoing[sid]) != 1 or stream_node[sid].kind is NodeKind.TARGET:
            continue
        successor = stream_outgoing[sid][0]
        if len(stream_incoming[successor]) != 1:
            continue
        merged_into[sid] = successor

    used_step_names = set(stream_query_name.values())
    stream_refs: dict[str, str] = {}
    stream_steps: dict[str, list[str]] = {}
    stream_results: dict[str, str] = {}
    source_bindings: list[str] = []
    transform_bindings: list[str] = []
    destination_bindings: list[str] = []
    outputs: list[str] = []
    uses_sql_transforms = any(_sql_query(node) for node in ordered)

    for sid in stream_order:
        node = stream_node[sid]
        query_name = stream_query_name[sid]
        sources = [stream_refs[up] for up in stream_incoming[sid]]
        if sid in router_plans:
            route_name, aliases, condition = router_plans[sid]
            steps, result_ident = _dataflow_router_branch_steps(
                route_name,
                sources[0],
                aliases,
                condition,
                used_step_names,
            )
        else:
            binding_key = (
                f"{key_prefix}/{node.native_id}" if key_prefix else node.native_id
            )
            node_steps_result = _dataflow_node_steps(
                node,
                query_name,
                sources,
                used_step_names,
                binding_key=binding_key,
            )
            if node_steps_result is None:
                return _scaffold(
                    asset, "dataflow", f"Unsupported {node.operation} configuration"
                )
            steps, result_ident = node_steps_result
            if node.kind is NodeKind.SOURCE:
                source_bindings.append(f"source_queries[{binding_key!r}]")
            if node.operation == "custom_transformation":
                transform_bindings.append(f"sql_transforms[{binding_key!r}]")
            if node.kind is NodeKind.TARGET:
                outputs.append(query_name)
                destination_bindings.append(f"destinations[{query_name!r}]")
        stream_steps[sid] = steps
        stream_results[sid] = result_ident
        stream_refs[sid] = result_ident if sid in merged_into else query_name

    anchor_steps: dict[str, list[str]] = {
        sid: [] for sid in stream_order if sid not in merged_into
    }
    for sid in stream_order:
        anchor = sid
        while anchor in merged_into:
            anchor = merged_into[anchor]
        anchor_steps[anchor].extend(stream_steps[sid])

    lines: list[str] = []
    definition_queries: list[str] = []
    for sid in stream_order:
        if sid in merged_into:
            continue
        query_name = stream_query_name[sid]
        definition_queries.append(query_name)
        lines.extend(
            [
                "",
                _format_m_query(
                    query_name,
                    anchor_steps[sid],
                    stream_results[sid],
                ),
            ]
        )

    return _CompiledMappingFragment(
        target="dataflow",
        lines=lines,
        definition_queries=definition_queries,
        source_bindings=source_bindings,
        transform_bindings=transform_bindings,
        destination_bindings=destination_bindings,
        outputs=outputs,
        uses_sql_transforms=uses_sql_transforms,
    )


def _unique_m_step(base: str, used: set[str]) -> str:
    candidate = base
    suffix = 1
    while candidate in used:
        suffix += 1
        candidate = f"{base}_{suffix}"
    used.add(candidate)
    return candidate


def _format_m_query(query_name: str, steps: list[str], result: str) -> str:
    if not steps:
        return f"shared {query_name} = {result};"
    formatted = ",\n".join("    " + step for step in steps)
    return f"shared {query_name} = let\n{formatted}\nin\n    {result};"


def _dataflow_router_plans(
    node: EtlNode,
    base_name: str,
) -> list[tuple[str, str, list[tuple[str, str]], str]] | None:
    raw_groups = node.properties.get("router_groups")
    if not isinstance(raw_groups, list):
        return None
    groups = [
        {
            "name": str(group.get("name", "")),
            "type": str(group.get("type", "")),
            "expression": str(group.get("expression", "")),
        }
        for group in raw_groups
        if isinstance(group, dict)
        and str(group.get("type", "")).startswith("OUTPUT")
        and str(group.get("name", ""))
    ]
    if not groups:
        return None
    translated_conditions: list[str] = []
    for group in groups:
        if group["type"] == "OUTPUT/DEFAULT":
            continue
        translated = _translate_powercenter_condition(
            group["expression"],
            "dataflow",
        )
        if translated is None:
            return None
        translated_conditions.append(translated)
    port_groups = _string_map(node.properties.get("port_groups"))
    ref_fields = _string_map(node.properties.get("port_ref_fields"))
    routes: list[tuple[str, str, list[tuple[str, str]], str]] = []
    used_names: set[str] = set()
    for group in groups:
        condition = (
            "not (" + " or ".join(f"({value})" for value in translated_conditions) + ")"
            if group["type"] == "OUTPUT/DEFAULT"
            else _translate_powercenter_condition(group["expression"], "dataflow")
        )
        if not condition:
            return None
        aliases = [
            (port.name, ref_fields[port.name])
            for port in node.ports
            if port.direction == "output"
            and port_groups.get(port.name) == group["name"]
            and port.name in ref_fields
        ]
        suffix = re.sub(r"[^A-Za-z0-9_]+", "_", group["name"]).strip("_").casefold()
        query_name = f"{base_name}_{suffix or 'route'}"
        if query_name in used_names:
            query_name = f"{query_name}_{len(used_names) + 1}"
        used_names.add(query_name)
        routes.append((group["name"], query_name, aliases, condition))
    return routes


def _dataflow_router_branch_steps(
    route_name: str,
    source: str,
    aliases: list[tuple[str, str]],
    condition: str,
    used_step_names: set[str],
) -> tuple[list[str], str]:
    if not aliases:
        return [f"{route_name} = Table.SelectRows({source}, each {condition})"], route_name
    steps: list[str] = []
    previous = source
    for index, (alias_name, ref_field) in enumerate(aliases, start=1):
        step = _unique_m_step(f"{route_name}_alias{index}", used_step_names)
        steps.append(
            f"{step} = Table.AddColumn("
            f"{previous}, {m_string(alias_name)}, each Record.Field(_, {m_string(ref_field)}))"
        )
        previous = step
    steps.append(f"{route_name} = Table.SelectRows({previous}, each {condition})")
    return steps, route_name


def _dataflow_node_steps(
    node: EtlNode,
    name: str,
    sources: list[str],
    used_step_names: set[str],
    *,
    binding_key: str | None = None,
) -> tuple[list[str], str] | None:
    key = binding_key or node.native_id
    if node.operation == "source":
        return [f"{name} = Record.Field(SourceBindings, {m_string(key)})"], name
    if len(sources) != 1:
        return None
    if node.operation in {"source_qualifier", "xml_source_qualifier", "target"}:
        return [], sources[0]
    if node.operation == "expression":
        fields = _expression_fields(node, "dataflow")
        if fields is None:
            return None
        if not fields:
            return [], sources[0]
        steps: list[str] = []
        previous = sources[0]
        for index, (field, expression) in enumerate(fields, start=1):
            step = (
                name
                if index == len(fields)
                else _unique_m_step(f"{name}_{index}", used_step_names)
            )
            steps.append(
                f"{step} = Table.AddColumn("
                f"{previous}, {m_string(field)}, each {expression})"
            )
            previous = step
        return steps, previous
    if node.operation == "aggregator":
        expression_types = _string_map(
            node.properties.get("port_expression_types")
        )
        group_fields = [
            port.name
            for port in node.ports
            if expression_types.get(port.name) == "GROUPBY"
        ]
        if not group_fields:
            return None
        columns = ", ".join(m_string(field) for field in group_fields)
        return (
            [
                f"{name} = Table.Distinct(Table.SelectColumns({sources[0]}, "
                f"{{{columns}}}))"
            ],
            name,
        )
    if node.operation == "custom_transformation":
        if not _sql_query(node):
            return None
        return (
            [
                f"{name} = Record.Field(SqlTransformBindings, {m_string(key)})"
                f"({sources[0]})"
            ],
            name,
        )
    if node.operation == "filter":
        condition = _condition(node)
        translated = _translate_condition(condition, "dataflow")
        if translated is None:
            return None
        return [f"{name} = Table.SelectRows({sources[0]}, each {translated})"], name
    raise AssertionError(f"Unexpected supported operation for {name}: {node.operation}")


def _notebook_router_statements(
    node: EtlNode,
    base_name: str,
    sources: list[str],
    *,
    binding_key: str | None = None,
) -> tuple[list[str], list[tuple[str, str]]] | None:
    if not sources:
        return None
    raw_groups = node.properties.get("router_groups")
    if not isinstance(raw_groups, list):
        return None
    groups = [
        str(group.get("name", ""))
        for group in raw_groups
        if isinstance(group, dict)
        and str(group.get("type", "")).startswith("OUTPUT")
        and str(group.get("name", ""))
    ]
    if not groups:
        return None
    routes_name = f"{base_name}_routes"
    arguments = ", ".join(sources)
    key = binding_key or node.native_id
    statements = [
        f'{routes_name} = require_transform({json.dumps(key)})({arguments})'
    ]
    outputs: list[tuple[str, str]] = []
    used_names: set[str] = set()
    for group in groups:
        suffix = re.sub(r"[^A-Za-z0-9_]+", "_", group).strip("_").casefold()
        query_name = f"{base_name}_{suffix or 'route'}"
        if query_name in used_names:
            query_name = f"{query_name}_{len(used_names) + 1}"
        used_names.add(query_name)
        statements.append(f"{query_name} = {routes_name}[{json.dumps(group)}]")
        outputs.append((group, query_name))
    return statements, outputs


def _notebook_statements(
    node: EtlNode,
    name: str,
    sources: list[str],
    *,
    binding_key: str | None = None,
) -> list[str] | None:
    key = binding_key or node.native_id
    if node.operation == "source":
        path_name = f"{name}_path"
        return [
            f"{path_name} = source_paths.get({key!r})",
            (
                f"if not {path_name}: raise ValueError("
                f'"Configure source_paths[{key!r}] before running")'
            ),
            f"{name} = _read_source({path_name})",
        ]
    if len(sources) != 1:
        return None
    if node.operation in {"source_qualifier", "xml_source_qualifier", "target"}:
        return [f"{name} = {sources[0]}"]
    if node.operation == "expression":
        fields = _expression_fields(node, "notebook")
        if fields is None:
            return None
        statement = f"{name} = {sources[0]}"
        for field, expression in fields:
            statement += f'.withColumn({json.dumps(field)}, {expression})'
        return [statement]
    if node.operation == "aggregator":
        expression_types = _string_map(
            node.properties.get("port_expression_types")
        )
        group_fields = [
            port.name
            for port in node.ports
            if expression_types.get(port.name) == "GROUPBY"
        ]
        if not group_fields:
            return None
        columns = ", ".join(json.dumps(field) for field in group_fields)
        return [f"{name} = {sources[0]}.select({columns}).dropDuplicates()"]
    if node.operation == "filter":
        translated = _translate_condition(_condition(node), "notebook")
        return [f"{name} = {sources[0]}.filter({translated})"] if translated else None
    return None


def _string_map(value: object) -> dict[str, str]:
    if not isinstance(value, dict):
        return {}
    return {
        str(key): str(item)
        for key, item in value.items()
        if isinstance(item, str)
    }


def _sql_query(node: EtlNode) -> str | None:
    metadata = _string_map(node.properties.get("metadata_extensions"))
    query = metadata.get("SQL_Query", "").strip()
    return query or None


def _condition(node: EtlNode) -> str:
    for key in ("condition", "Filter Condition", "filterCondition"):
        value = node.properties.get(key)
        if isinstance(value, str) and value.strip():
            return value.strip()
    return ""


def _expression_fields(
    node: EtlNode,
    target: Literal["dataflow", "notebook"],
) -> list[tuple[str, str]] | None:
    fields: list[tuple[str, str]] = []
    for port in node.ports:
        if port.direction == "input" or not port.expression:
            continue
        expression = port.expression.strip()
        if expression.casefold() == port.name.casefold():
            continue
        translated = _translate_powercenter_expression(expression, target)
        if translated is None:
            return None
        fields.append((port.name, translated))
    return fields


def _translate_powercenter_expression(
    expression: str,
    target: Literal["dataflow", "notebook"],
) -> str | None:
    value = expression.strip()
    if value.casefold() == "sysdate":
        return "DateTime.LocalNow()" if target == "dataflow" else "F.current_timestamp()"

    string_match = re.fullmatch(r"'([^']*)'|\"([^\"]*)\"", value)
    if string_match:
        raw = (
            string_match.group(1)
            if string_match.group(1) is not None
            else string_match.group(2)
        )
        return m_string(raw) if target == "dataflow" else f"F.lit({json.dumps(raw)})"

    if re.fullmatch(r"-?\d+(?:\.\d+)?", value):
        return value if target == "dataflow" else f"F.lit({value})"

    if value.casefold() == "null":
        return "null" if target == "dataflow" else "F.lit(None)"

    iif_arguments = _function_arguments(value, "IIF")
    if iif_arguments is not None and len(iif_arguments) == 3:
        condition = _translate_powercenter_condition(iif_arguments[0], target)
        when_true = _translate_powercenter_expression(iif_arguments[1], target)
        when_false = _translate_powercenter_expression(iif_arguments[2], target)
        if condition is None or when_true is None or when_false is None:
            return None
        if target == "dataflow":
            return f"if {condition} then {when_true} else {when_false}"
        return f"F.when({condition}, {when_true}).otherwise({when_false})"

    is_date = re.fullmatch(
        r"(?i)IS_DATE\(\s*([A-Za-z_][A-Za-z0-9_]*)\s*,\s*"
        r"['\"]YYYYMMDD['\"]\s*\)",
        value,
    )
    if is_date:
        field_name = is_date.group(1)
        if target == "dataflow":
            return (
                "if (try Date.FromText("
                f'Text.From(Record.Field(_, "{field_name}")), '
                '[Format="yyyyMMdd", Culture="en-US"]) '
                'otherwise null) <> null then "1" else "0"'
            )
        return (
            f'F.when(F.to_date(F.col("{field_name}"), "yyyyMMdd").isNotNull(), '
            'F.lit("1")).otherwise(F.lit("0"))'
        )

    month_date = re.fullmatch(
        r"(?i)TRUNC\(\s*TO_DATE\(\s*([A-Za-z_][A-Za-z0-9_]*)\s*,\s*"
        r"['\"]YYYYMMDD['\"]\s*\)\s*,\s*['\"]MM['\"]\s*\)",
        value,
    )
    if month_date:
        field_name = month_date.group(1)
        if target == "dataflow":
            return (
                "try Date.StartOfMonth(Date.FromText("
                f'Text.From(Record.Field(_, "{field_name}")), '
                '[Format="yyyyMMdd", Culture="en-US"])) otherwise null'
            )
        return f'F.trunc(F.to_date(F.col("{field_name}"), "yyyyMMdd"), "month")'

    date_text = re.fullmatch(
        r"(?i)TO_CHAR\(\s*([A-Za-z_][A-Za-z0-9_]*)\s*,\s*"
        r"['\"]YYYYMMDD['\"]\s*\)",
        value,
    )
    if date_text:
        field_name = date_text.group(1)
        if target == "dataflow":
            return (
                f'try Date.ToText(Date.From(Record.Field(_, "{field_name}")), '
                '"yyyyMMdd") otherwise null'
            )
        return f'F.date_format(F.col("{field_name}"), "yyyyMMdd")'

    if target == "dataflow":
        basename = re.fullmatch(
            r"(?i)SUBSTR\(\s*([A-Za-z_][A-Za-z0-9_]*)\s*,\s*"
            r"INSTR\(\s*([A-Za-z_][A-Za-z0-9_]*)\s*,\s*'/'\s*,\s*-1\s*,\s*1\s*\)"
            r"\s*\+\s*1\s*\)",
            value,
        )
        if basename and basename.group(1) == basename.group(2):
            field_name = basename.group(1)
            return (
                "List.Last(Text.Split("
                f'Text.From(Record.Field(_, "{field_name}")), "/"))'
            )

        file_date = re.fullmatch(
            r"(?i)SUBSTR\(\s*([A-Za-z_][A-Za-z0-9_]*)\s*,\s*"
            r"INSTR\(\s*([A-Za-z_][A-Za-z0-9_]*)\s*,\s*'_'\s*,\s*-1\s*,\s*1\s*\)"
            r"\s*\+\s*1\s*,\s*"
            r"INSTR\(\s*([A-Za-z_][A-Za-z0-9_]*)\s*,\s*'\.'\s*,\s*1\s*,\s*1\s*\)"
            r"\s*-\s*INSTR\(\s*([A-Za-z_][A-Za-z0-9_]*)\s*,\s*'_'\s*,\s*-1\s*,\s*1\s*\)"
            r"\s*-\s*1\s*\)",
            value,
        )
        if file_date and len(set(file_date.groups())) == 1:
            field_name = file_date.group(1)
            return (
                "Text.BeforeDelimiter(List.Last(Text.Split("
                f'Text.From(Record.Field(_, "{field_name}")), "_")), ".")'
            )

        path_segment = re.fullmatch(
            r"(?i)SUBSTR\(\s*([A-Za-z_][A-Za-z0-9_]*)\s*,\s*"
            r"INSTR\(\s*([A-Za-z_][A-Za-z0-9_]*)\s*,\s*'/'\s*,\s*-1\s*,\s*3\s*\)"
            r"\s*\+\s*1\s*,\s*"
            r"INSTR\(\s*([A-Za-z_][A-Za-z0-9_]*)\s*,\s*'/'\s*,\s*-1\s*,\s*2\s*\)"
            r"\s*-\s*INSTR\(\s*([A-Za-z_][A-Za-z0-9_]*)\s*,\s*'/'\s*,\s*-1\s*,\s*3\s*\)"
            r"\s*-\s*1\s*\)",
            value,
        )
        if path_segment and len(set(path_segment.groups())) == 1:
            field_name = path_segment.group(1)
            return (
                "let Segments = Text.Split("
                f'Text.From(Record.Field(_, "{field_name}")), "/") '
                "in Segments{List.Count(Segments) - 3}"
            )

    field = _trimmed_field(value)
    if field is not None:
        if target == "dataflow":
            return f'Text.Trim(Text.From(Record.Field(_, "{field}")))'
        return f'F.trim(F.col("{field}"))'

    date_match = re.fullmatch(
        r"(?i)to_date\(\s*(.+?)\s*,\s*['\"]DD-MON-YYYY['\"]\s*\)",
        value,
    )
    if date_match:
        date_source = date_match.group(1).strip()
        date_field = _trimmed_field(date_source) or (
            date_source
            if re.fullmatch(r"[A-Za-z_][A-Za-z0-9_]*", date_source)
            else None
        )
        if date_field is None:
            return None
        if target == "dataflow":
            return (
                "try Date.FromText("
                f'Text.Trim(Text.From(Record.Field(_, "{date_field}"))), '
                '[Format="dd-MMM-yyyy", Culture="en-US"]) otherwise null'
            )
        return f'F.to_date(F.col("{date_field}"), "dd-MMM-yyyy")'

    operands = [
        item.strip()
        for item in value.split("+")
        if item.strip()
    ]
    if len(operands) > 1 and all(
        re.fullmatch(r"[A-Za-z_][A-Za-z0-9_]*", item) for item in operands
    ):
        if target == "dataflow":
            return " + ".join(
                f'Number.From(Record.Field(_, "{item}"))' for item in operands
            )
        return " + ".join(f'F.col("{item}")' for item in operands)

    if re.fullmatch(r"[A-Za-z_][A-Za-z0-9_]*", value):
        if target == "dataflow":
            return f'Record.Field(_, "{value}")'
        return f'F.col("{value}")'
    return None


def _function_arguments(value: str, name: str) -> list[str] | None:
    prefix = f"{name}("
    if not value.upper().startswith(prefix) or not value.endswith(")"):
        return None
    content = value[len(prefix) : -1]
    arguments: list[str] = []
    start = 0
    depth = 0
    quote: str | None = None
    for index, character in enumerate(content):
        if quote is not None:
            if character == quote:
                quote = None
            continue
        if character in {"'", '"'}:
            quote = character
        elif character == "(":
            depth += 1
        elif character == ")":
            depth -= 1
        elif character == "," and depth == 0:
            arguments.append(content[start:index].strip())
            start = index + 1
    if quote is not None or depth != 0:
        return None
    arguments.append(content[start:].strip())
    return arguments


def _trimmed_field(expression: str) -> str | None:
    match = re.fullmatch(
        r"(?i)LTRIM\(\s*RTRIM\(\s*([A-Za-z_][A-Za-z0-9_]*)\s*\)\s*\)",
        expression.strip(),
    )
    if match:
        return match.group(1)
    match = re.fullmatch(
        r"(?i)RTRIM\(\s*LTRIM\(\s*([A-Za-z_][A-Za-z0-9_]*)\s*\)\s*\)",
        expression.strip(),
    )
    return match.group(1) if match else None


def _translate_powercenter_condition(
    expression: str,
    target: Literal["dataflow", "notebook"],
) -> str | None:
    value = expression.strip()
    parts = re.split(r"(?i)\s+AND\s+", value)
    if len(parts) > 1:
        translated = [
            _translate_powercenter_condition(part, target) for part in parts
        ]
        if any(part is None for part in translated):
            return None
        operator = " and " if target == "dataflow" else " & "
        return operator.join(f"({part})" for part in translated if part is not None)

    not_null = re.fullmatch(
        r"(?i)NOT\(\s*ISNULL\(\s*([A-Za-z_][A-Za-z0-9_]*)\s*\)\s*\)",
        value,
    )
    if not_null:
        field = not_null.group(1)
        if target == "dataflow":
            return f'Record.Field(_, "{field}") <> null'
        return f'F.col("{field}").isNotNull()'

    is_null = re.fullmatch(
        r"(?i)ISNULL\(\s*([A-Za-z_][A-Za-z0-9_]*)\s*\)",
        value,
    )
    if is_null:
        field = is_null.group(1)
        if target == "dataflow":
            return f'Record.Field(_, "{field}") = null'
        return f'F.col("{field}").isNull()'
    return _translate_condition(value, target)


def _translate_condition(
    expression: str,
    target: Literal["dataflow", "notebook"],
) -> str | None:
    match = re.fullmatch(
        r"\[?([A-Za-z_][A-Za-z0-9_]*)\]?\s*(>=|<=|!=|==|=|>|<)\s*"
        r"(?:'([^']*)'|\"([^\"]*)\"|(-?\d+(?:\.\d+)?))",
        expression.strip(),
    )
    if not match:
        return None
    field, operator, single, double, number = match.groups()
    value = single if single is not None else double if double is not None else number
    assert value is not None
    is_number = number is not None
    if target == "dataflow":
        m_operator = "<>" if operator == "!=" else "=" if operator in {"=", "=="} else operator
        literal = value if is_number else m_string(value)
        return f'Record.Field(_, "{field}") {m_operator} {literal}'
    py_operator = "==" if operator == "=" else operator
    literal = value if is_number else json.dumps(value)
    return f'F.col("{field}") {py_operator} F.lit({literal})'


def _topological_nodes(graph: EtlGraph) -> list[EtlNode] | None:
    by_id = {node.native_id: node for node in graph.nodes}
    incoming = dict.fromkeys(by_id, 0)
    outgoing: dict[str, list[str]] = {identity: [] for identity in by_id}
    for edge in graph.edges:
        incoming[edge.target] += 1
        outgoing[edge.source].append(edge.target)
    order_index = {node.native_id: index for index, node in enumerate(graph.nodes)}
    queue = sorted(
        (identity for identity, count in incoming.items() if count == 0),
        key=order_index.__getitem__,
    )
    ordered: list[EtlNode] = []
    while queue:
        identity = queue.pop(0)
        ordered.append(by_id[identity])
        for target in outgoing[identity]:
            incoming[target] -= 1
            if incoming[target] == 0:
                queue.append(target)
                queue.sort(key=order_index.__getitem__)
    return ordered if len(ordered) == len(graph.nodes) else None


def _query_names(
    nodes: list[EtlNode],
    *,
    prefix: str | None = None,
) -> dict[str, str]:
    names: dict[str, str] = {}
    used: set[str] = set()
    for node in nodes:
        base = re.sub(r"[^A-Za-z0-9_]+", "_", node.name).strip("_").casefold()
        if not base:
            base = "stage"
        if prefix:
            base = f"{prefix}_{base}"
        elif base[0].isdigit():
            base = f"stage_{base}"
        name = base if base not in used else f"{base}_{node.native_id}"
        used.add(name)
        names[node.native_id] = name
    return names


def _node_name(identity: str, graph: EtlGraph) -> str:
    return next(
        (node.name for node in graph.nodes if node.native_id == identity),
        identity,
    )


def _fail_closed_m(candidate: EtlCompiledCandidate) -> EtlCompiledCandidate:
    """Scaffold dataflow output whose Power Query text is not lexically valid."""
    if (
        candidate.target != "dataflow"
        or candidate.validation_state != "generated_unvalidated"
        or m_text_is_well_formed(candidate.code)
    ):
        return candidate
    message = "Generated Power Query M is not well-formed"
    return EtlCompiledCandidate(
        asset_id=candidate.asset_id,
        name=candidate.name,
        target=candidate.target,
        validation_state="scaffold",
        deployable=False,
        runtime_ready=False,
        code=message,
        diagnostics=(*candidate.diagnostics, message),
        required_bindings=candidate.required_bindings,
    )


def _scaffold(
    asset: EtlAsset,
    target: CompilationTarget,
    diagnostic: str,
) -> EtlCompiledCandidate:
    return EtlCompiledCandidate(
        asset_id=asset.native_id,
        name=asset.name,
        target=target,
        validation_state="scaffold",
        deployable=False,
        runtime_ready=False,
        code="",
        diagnostics=(diagnostic,),
        required_bindings=("manual implementation for unsupported ETL semantics",),
    )

