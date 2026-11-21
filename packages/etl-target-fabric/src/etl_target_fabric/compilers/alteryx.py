"""Local review candidates for an explicitly bounded compiler subset."""

import hashlib
import heapq
import html
import json
import re
import uuid
from dataclasses import dataclass
from pathlib import Path
from typing import Literal
from xml.etree.ElementTree import fromstring

from pydantic import BaseModel, Field

from etl_migration_core.contracts.ir import AssetType, SourcePlatform
from etl_migration_core.sources.alteryx import AlteryxSourceAdapter
from etl_migration_core.sources.alteryx.graph import (
    GRAPH_VERSION,
    GraphNode,
    WorkflowGraph,
    WorkflowParseError,
)
from etl_target_fabric.assessment.support_matrix import (
    REGISTRY_VERSION,
    RULES_VERSION,
)
from etl_target_fabric.assessment.support_matrix import (
    alteryx_support_for as _support_for,
)

COMPILER_VERSION = "2.3.0"
Target = Literal["notebook", "dataflow", "pipeline"]


class DataflowQueryGroup(BaseModel):
    """A Fabric query group derived from an Alteryx ToolContainer."""

    id: str
    name: str
    description: str
    parent_id: str | None = None
    order: int


class Candidate(BaseModel):
    """A native translation or explicit migration scaffold."""

    workflow: str
    target: Target
    validation_state: Literal["blocked", "generated_unvalidated", "scaffold"]
    translation_mode: Literal["native", "scaffold"] = "native"
    deployable: bool = False
    definition_ready: bool = False
    runtime_ready: bool = False
    source_sha256: str
    code_sha256: str
    compiler_version: str = COMPILER_VERSION
    graph_version: str = GRAPH_VERSION
    registry_version: str = REGISTRY_VERSION
    rules_version: str = RULES_VERSION
    code: str = ""
    diagnostics: list[str] = Field(default_factory=list)
    required_bindings: list[str] = Field(default_factory=list)
    artifact_path: str | None = None
    definition_files: list[str] = Field(default_factory=list)
    definition_queries: list[str] = Field(default_factory=list)
    loaded_queries: list[str] = Field(default_factory=list)
    query_groups: list[DataflowQueryGroup] = Field(default_factory=list)
    query_group_assignments: dict[str, str] = Field(default_factory=dict)
    source_platform: SourcePlatform = SourcePlatform.ALTERYX
    source_product: str = "Alteryx Designer"
    asset_type: AssetType = AssetType.WORKFLOW
    native_id: str | None = None
    folder: str | None = None


@dataclass(frozen=True)
class DagCompilation:
    code: str
    required_bindings: list[str]
    definition_queries: list[str]
    loaded_queries: list[str]
    query_groups: list[DataflowQueryGroup]
    query_group_assignments: dict[str, str]


def generate_candidate(path: Path, target: Target) -> Candidate:
    """Compile review-only transformations without executing source content."""
    diagnostics: list[str] = []
    statements: list[str] = []
    required_bindings: list[str] = []
    try:
        graph = AlteryxSourceAdapter().legacy_graph(path)
        if target == "pipeline":
            message = (
                "Alteryx pipeline generation is available only for mixed-item bundles"
            )
            return Candidate(
                workflow=path.name,
                target=target,
                validation_state="scaffold",
                translation_mode="scaffold",
                source_sha256=graph.sha256,
                code_sha256=hashlib.sha256(message.encode()).hexdigest(),
                code=message,
                diagnostics=[message],
            )
        diagnostics.extend(graph.execution_issues)
        if graph.dependencies:
            diagnostics.append("Macro dependencies require independent redesign")
        if any(node.disabled for node in graph.nodes):
            diagnostics.append("Disabled-branch semantics are outside compiler coverage")
        executable = tuple(
            node
            for node in graph.nodes
            if _support_for(node.plugin) != "neutral" or node.name.casefold() == "browse"
        )
        executable_ids = {node.id for node in executable}
        if any(
            source not in executable_ids or destination not in executable_ids
            for source, destination, _ in graph.edges
        ):
            diagnostics.append("Connections to context-only nodes are unsupported")
        nodes = _linear_nodes(executable, graph.edges)
        if target == "dataflow" or not nodes:
            dag_result = (
                _compile_supported_dag(
                    executable,
                    graph.nodes,
                    graph.edges,
                    target,
                    graph.sha256,
                )
                if not diagnostics
                else None
            )
            if dag_result is not None:
                return Candidate(
                    workflow=path.name,
                    target=target,
                    validation_state="generated_unvalidated",
                    deployable=True,
                    definition_ready=True,
                    runtime_ready=not dag_result.required_bindings,
                    source_sha256=graph.sha256,
                    code_sha256=hashlib.sha256(dag_result.code.encode()).hexdigest(),
                    code=dag_result.code,
                    required_bindings=[
                        *dag_result.required_bindings,
                        "independent semantic parity",
                    ],
                    definition_queries=dag_result.definition_queries,
                    loaded_queries=dag_result.loaded_queries,
                    query_groups=dag_result.query_groups,
                    query_group_assignments=dag_result.query_group_assignments,
                )
            diagnostics.append("Only a supported linear or Union/CrossTab graph is native")
            if target == "dataflow":
                nodes = []
        for index, node in enumerate(nodes):
            diagnostics.extend(f"Tool {node.id}: {issue}" for issue in node.issues)
            operation = node.name.casefold()
            if _support_for(node.plugin) == "manual":
                diagnostics.append(f"Tool {node.id}: unrecognized plugin identity")
                continue
            if index == 0 and operation not in {"inputdata", "dbfileinput", "textinput"}:
                diagnostics.append("A reviewed source binding is required at the graph root")
            allowed = {
                "inputdata": {"File", "FormatSpecificOptions", "Passwords"},
                "dbfileinput": {"File", "FormatSpecificOptions", "Passwords"},
                "textinput": {"NumRows", "Fields", "Data"},
                "filter": {"Expression", "Mode", "Simple"},
                "alteryxselect": {"OrderChanged", "CommaDecimal", "SelectFields"},
                "select": {"OrderChanged", "CommaDecimal", "SelectFields"},
                "formula": {"FormulaFields"},
                "sort": {"SortInfo"},
                "sample": {"Mode", "N", "GroupFields"},
                "unique": {"UniqueFields"},
                "recordid": {"FieldName", "StartValue", "FieldType", "FieldSize", "Position"},
                "autofield": {"Fields"},
                "datetime": {"IsFrom", "InputFieldName", "Format", "OutputFieldName"},
                "regex": {
                    "Field",
                    "RegExExpression",
                    "CaseInsensitve",
                    "Method",
                    "Replace",
                    "ParseSimple",
                    "ParseComplex",
                    "Match",
                },
                "outputdata": {"File", "FormatSpecificOptions", "Passwords", "MultiFile"},
                "dbfileoutput": {"File", "FormatSpecificOptions", "Passwords", "MultiFile"},
                "browse": set(),
            }
            if operation not in allowed:
                diagnostics.append(f"Tool {node.id}: {node.name} has no compiler coverage")
                continue
            if set(node.configuration) - allowed[operation]:
                diagnostics.append(f"Tool {node.id}: unsupported configuration")
                continue
            if operation in {"inputdata", "dbfileinput"}:
                if index != 0:
                    diagnostics.append("Multiple source nodes are not supported")
                required_bindings.append(f"source_paths[{node.id!r}]")
                if target == "notebook":
                    statements.extend(
                        [
                            "source_paths = globals().get('source_paths', {})",
                            f"source_path = source_paths.get({node.id!r})",
                            f"if not source_path: raise ValueError("
                            f'"Configure source_paths[{node.id!r}] before running")',
                            "df = spark.read.option('header', True).option('inferSchema', True)"
                            ".csv(source_path)",
                        ]
                    )
                else:
                    statements.append(
                        f"    Source = Record.Field(SourceBindings, {_m_string(node.id)})"
                    )
            elif operation == "textinput":
                if index != 0:
                    diagnostics.append("Multiple source nodes are not supported")
                fields, rows = _text_input(node, diagnostics)
                if target == "notebook":
                    statements.append(
                        f"df = spark.createDataFrame({json.dumps(rows)}, {json.dumps(fields)})"
                    )
                else:
                    m_rows = ", ".join(
                        "{" + ", ".join(_m_value(value) for value in row) + "}" for row in rows
                    )
                    columns = ", ".join(_m_string(field) for field in fields)
                    statements.append(f"    Source = #table({{{columns}}}, {{{m_rows}}})")
            elif operation == "filter":
                expression = _filter_expression(node)
                translated = _translate_expression(expression, target)
                if translated is None:
                    diagnostics.append(
                        f"Tool {node.id}: unsupported filter expression {expression!r}"
                    )
                    continue
                if target == "notebook":
                    statements.append(f"df = df.filter({translated})")
                else:
                    statements.append(
                        f"    Step{index} = Table.SelectRows(Previous, each {translated})"
                    )
            elif operation in {"select", "alteryxselect"}:
                select_fields = fromstring(
                    node.configuration.get("SelectFields", "<SelectFields/>")
                )
                selected: list[str] = []
                wildcard = False
                for select_field in select_fields:
                    if (
                        set(select_field.attrib) - {"field", "selected"}
                        or select_field.get("selected") not in {"True", "False"}
                        or (
                            select_field.get("field", "").startswith("*")
                            and select_field.get("field") != "*Unknown"
                        )
                    ):
                        diagnostics.append(f"Tool {node.id}: unsupported field-selection rules")
                    elif (
                        select_field.get("field") == "*Unknown"
                        and select_field.get("selected") == "True"
                    ):
                        wildcard = True
                    elif select_field.get("selected") == "True":
                        selected.append(select_field.get("field", ""))
                if not selected and not wildcard:
                    diagnostics.append(f"Tool {node.id}: explicit selected fields are required")
                elif wildcard and not selected:
                    statements.append(
                        "df = df" if target == "notebook" else f"    Step{index} = Previous"
                    )
                elif target == "notebook":
                    statements.append(f"df = df.select(*{json.dumps(selected)})")
                else:
                    columns = ", ".join(_m_string(field) for field in selected)
                    statements.append(
                        f"    Step{index} = Table.SelectColumns(Previous, {{{columns}}})"
                    )
            elif operation == "formula":
                formulas = fromstring(node.configuration["FormulaFields"])
                for formula in formulas:
                    formula_field = formula.get("field", "")
                    expression = formula.get("expression", "")
                    translated = _translate_expression(expression, target)
                    if not formula_field or translated is None:
                        diagnostics.append(
                            f"Tool {node.id}: unsupported formula {formula_field}={expression!r}"
                        )
                    elif target == "notebook":
                        statements.append(
                            f"df = df.withColumn({json.dumps(formula_field)}, {translated})"
                        )
                    else:
                        statements.append(
                            f"    Step{index}_{len(statements)} = Table.AddColumn("
                            f"Previous, {_m_string(formula_field)}, each {translated})"
                        )
            elif operation == "sort":
                sort_fields = fromstring(node.configuration["SortInfo"])
                specs = [
                    (sort_field.get("field", ""), sort_field.get("order", "Ascending"))
                    for sort_field in sort_fields
                ]
                if not specs or any(not name for name, _ in specs):
                    diagnostics.append(f"Tool {node.id}: invalid sort fields")
                elif target == "notebook":
                    values = ", ".join(
                        f"F.col({json.dumps(name)})."
                        f"{'desc' if order.casefold() == 'descending' else 'asc'}()"
                        for name, order in specs
                    )
                    statements.append(f"df = df.orderBy({values})")
                else:
                    values = ", ".join(
                        "{" + f"{_m_string(name)}, Order."
                        f"{'Descending' if order.casefold() == 'descending' else 'Ascending'}" + "}"
                        for name, order in specs
                    )
                    statements.append(f"    Step{index} = Table.Sort(Previous, {{{values}}})")
            elif operation == "sample":
                mode, count = _text(node, "Mode"), _int_text(node, "N")
                if mode != "First" or count is None:
                    diagnostics.append(f"Tool {node.id}: only First N sampling is supported")
                elif target == "notebook":
                    statements.append(f"df = df.limit({count})")
                else:
                    statements.append(f"    Step{index} = Table.FirstN(Previous, {count})")
            elif operation == "unique":
                unique_fields = fromstring(node.configuration["UniqueFields"])
                names = [unique_field.get("field", "") for unique_field in unique_fields]
                if not names or any(not name for name in names):
                    diagnostics.append(f"Tool {node.id}: invalid unique fields")
                elif target == "notebook":
                    statements.append(f"df = df.dropDuplicates({json.dumps(names)})")
                else:
                    statements.append(
                        f"    Step{index} = Table.Distinct(Previous, "
                        f"{{{', '.join(_m_string(name) for name in names)}}})"
                    )
            elif operation == "recordid":
                record_field, start = _text(node, "FieldName"), _int_text(node, "StartValue")
                if not record_field or start is None:
                    diagnostics.append(f"Tool {node.id}: invalid RecordID configuration")
                elif target == "notebook":
                    statements.append(
                        "df = df.withColumn("
                        f"{json.dumps(record_field)}, "
                        f"F.monotonically_increasing_id() + {start})"
                    )
                else:
                    statements.append(
                        f"    Step{index} = Table.AddIndexColumn(Previous, "
                        f"{_m_string(record_field)}, {start}, 1, Int64.Type)"
                    )
            elif operation == "autofield":
                statements.append(
                    "df = df" if target == "notebook" else f"    Step{index} = Previous"
                )
            elif operation == "datetime":
                source_field = _text(node, "InputFieldName")
                output_field = _text(node, "OutputFieldName")
                format_string = _text(node, "Format")
                if (
                    target != "notebook"
                    or _text(node, "IsFrom").casefold() != "true"
                    or not source_field
                    or not output_field
                    or not format_string
                ):
                    diagnostics.append(
                        f"Tool {node.id}: DateTime conversion is supported only in Notebook"
                    )
                else:
                    statements.append(
                        f"df = df.withColumn({json.dumps(output_field)}, "
                        f"F.to_date(F.col({json.dumps(source_field)}), "
                        f"{json.dumps(format_string)}))"
                    )
            elif operation == "regex":
                regex_fields = fromstring(node.configuration["ParseComplex"])
                source_field = _text(node, "Field")
                pattern = _text(node, "RegExExpression")
                outputs = [field.get("field", "") for field in regex_fields]
                if (
                    target != "notebook"
                    or _text(node, "Method") != "ParseComplex"
                    or not source_field
                    or not pattern
                    or not outputs
                    or any(not field for field in outputs)
                ):
                    diagnostics.append(
                        f"Tool {node.id}: RegEx ParseComplex is supported only in Notebook"
                    )
                else:
                    if _text(node, "CaseInsensitve").casefold() == "true":
                        pattern = "(?i)" + pattern
                    for group, output_field in enumerate(outputs, start=1):
                        statements.append(
                            f"df = df.withColumn({json.dumps(output_field)}, "
                            f"F.regexp_extract(F.col({json.dumps(source_field)}), "
                            f"{json.dumps(pattern)}, {group}))"
                        )
            elif index != len(nodes) - 1:
                diagnostics.append("Output/Browse must be terminal")
        if diagnostics:
            code = _migration_scaffold(graph, target, diagnostics)
            required_bindings.append("manual implementation for unsupported Alteryx semantics")
        else:
            code = ""
            if target == "notebook":
                code = (
                    "from pyspark.sql import functions as F\n\n"
                    + "\n".join(statements)
                    + "\n\ndisplay(df)\n"
                )
            else:
                previous = "Source"
                normalized: list[str] = []
                for statement in statements:
                    statement = re.sub(r"\bPrevious\b", previous, statement, count=1)
                    previous = statement.strip().split(" =", 1)[0]
                    normalized.append(statement)
                code = (
                    "let\n"
                    + (
                        '    SourceBindings = error "Configure source bindings before refresh",\n'
                        if required_bindings
                        else ""
                    )
                    + ",\n".join(normalized)
                    + f"\nin\n    {previous}\n"
                )
        return Candidate(
            workflow=path.name,
            target=target,
            validation_state="scaffold" if diagnostics else "generated_unvalidated",
            translation_mode="scaffold" if diagnostics else "native",
            deployable=not diagnostics,
            definition_ready=not diagnostics,
            runtime_ready=not diagnostics and not required_bindings,
            source_sha256=graph.sha256,
            code_sha256=hashlib.sha256(code.encode()).hexdigest(),
            code=code,
            diagnostics=diagnostics,
            required_bindings=[*required_bindings, "independent semantic parity"],
        )
    except WorkflowParseError as error:
        return Candidate(
            workflow=path.name,
            target=target,
            validation_state="blocked",
            source_sha256="",
            code_sha256=hashlib.sha256(b"").hexdigest(),
            diagnostics=[str(error)],
        )


def _migration_scaffold(
    graph: WorkflowGraph, target: Target, diagnostics: list[str]
) -> str:
    bounded_diagnostics = diagnostics[:100]
    if len(diagnostics) > len(bounded_diagnostics):
        bounded_diagnostics.append(
            f"{len(diagnostics) - len(bounded_diagnostics)} additional diagnostics omitted"
        )
    if target == "dataflow":
        rows = ", ".join(
            "{"
            + f'{_m_string("Manual implementation required")}, {_m_string(diagnostic)}'
            + "}"
            for diagnostic in bounded_diagnostics
        )
        return (
            "let\n"
            "    MigrationScaffold = #table("
            '{"Status", "Diagnostic"}, '
            f"{{{rows}}})\n"
            "in\n"
            "    MigrationScaffold\n"
        )

    graph_payload = {
        "schema_version": graph.schema_version,
        "nodes": [
            {
                "id": node.id,
                "name": node.name,
                "plugin": node.plugin,
                "disabled": node.disabled,
            }
            for node in graph.nodes[:500]
        ],
        "edges": [
            {"source": source, "target": destination, "anchor": anchor}
            for source, destination, anchor in graph.edges[:1000]
        ],
        "dependencies": list(graph.dependencies),
        "truncated": len(graph.nodes) > 500 or len(graph.edges) > 1000,
    }
    return (
        "import json\n\n"
        f"migration_graph = json.loads({json.dumps(graph_payload, sort_keys=True)!r})\n"
        f"migration_diagnostics = json.loads({json.dumps(bounded_diagnostics)!r})\n\n"
        'raise RuntimeError("Migration scaffold requires implementation and parity validation")\n'
    )


def _compile_supported_dag(
    nodes: tuple[GraphNode, ...],
    all_nodes: tuple[GraphNode, ...],
    edges: tuple[tuple[str, str, str], ...],
    target: Target,
    source_sha256: str,
) -> DagCompilation | None:
    allowed = {
        "alteryxselect",
        "appendfields",
        "datetime",
        "dbfileinput",
        "filter",
        "inputdata",
        "textinput",
        "formula",
        "join",
        "multirowformula",
        "recordid",
        "regex",
        "sample",
        "select",
        "sort",
        "summarize",
        "transpose",
        "union",
        "unique",
        "crosstab",
        "autofield",
        "outputdata",
        "dbfileoutput",
        "browse",
    }
    if not nodes or any(node.name.casefold() not in allowed for node in nodes):
        return None
    by_id = {node.id: node for node in nodes}
    incoming: dict[str, list[str]] = {node.id: [] for node in nodes}
    outgoing: dict[str, list[str]] = {node.id: [] for node in nodes}
    for source, destination, _ in edges:
        if source not in by_id or destination not in by_id:
            return None
        incoming[destination].append(source)
        outgoing[source].append(destination)
    order_index = {node.id: index for index, node in enumerate(nodes)}
    queue = [
        (order_index[node.id], node.id)
        for node in nodes
        if not incoming[node.id]
    ]
    heapq.heapify(queue)
    ordered: list[GraphNode] = []
    remaining = {node.id: len(incoming[node.id]) for node in nodes}
    while queue:
        _, identity = heapq.heappop(queue)
        ordered.append(by_id[identity])
        for destination in outgoing[identity]:
            remaining[destination] -= 1
            if remaining[destination] == 0:
                heapq.heappush(queue, (order_index[destination], destination))
    if len(ordered) != len(nodes):
        return None

    variable_names: dict[str, str] = {}
    used_names: set[str] = set()
    for node in ordered:
        base_name = _python_variable(node.label or node.name)
        variable_name = base_name
        if variable_name in used_names:
            variable_name = f"{base_name}_{node.id}"
        used_names.add(variable_name)
        variable_names[node.id] = variable_name

    terminals = [node.id for node in nodes if not outgoing[node.id]]
    if not terminals:
        return None
    output_operations = {"outputdata", "dbfileoutput", "browse"}
    loaded_node_ids = {
        terminal
        for terminal in terminals
        if by_id[terminal].name.casefold() in output_operations
    } or set(terminals)
    query_groups: list[DataflowQueryGroup] = []
    all_assignments: dict[str, str] = {}
    merged_into: dict[str, str] = {}
    if target == "dataflow":
        query_groups, all_assignments = _dataflow_query_groups(
            all_nodes,
            variable_names,
            source_sha256,
        )
        for node in ordered:
            if len(outgoing[node.id]) != 1 or node.id in loaded_node_ids:
                continue
            successor = outgoing[node.id][0]
            if len(incoming[successor]) != 1:
                continue
            if all_assignments.get(variable_names[node.id]) != all_assignments.get(
                variable_names[successor]
            ):
                continue
            merged_into[node.id] = successor

    used_step_names = set(used_names)
    statements: list[str] = []
    references: dict[str, str] = {}
    sort_fields: dict[str, list[tuple[str, str]]] = {}
    node_steps: dict[str, list[str]] = {}
    node_results: dict[str, str] = {}
    required_bindings: list[str] = []
    diagnostics: list[str] = []
    for node in ordered:
        statement_start = len(statements)
        operation = node.name.casefold()
        source_ids = incoming[node.id]
        sources = [references[source] for source in source_ids if source in references]
        if len(sources) != len(source_ids):
            return None
        name = variable_names[node.id]
        if operation == "textinput":
            if sources:
                return None
            fields, rows = _text_input(node, diagnostics)
            if diagnostics:
                return None
            if target == "notebook":
                statements.append(
                    f"{name} = spark.createDataFrame({json.dumps(rows)}, {json.dumps(fields)})"
                )
            else:
                columns = ", ".join(_m_string(field) for field in fields)
                m_rows = ", ".join(
                    "{" + ", ".join(_m_value(value) for value in row) + "}"
                    for row in rows
                )
                statements.append(f"    {name} = #table({{{columns}}}, {{{m_rows}}})")
            references[node.id] = name
        elif operation in {"dbfileinput", "inputdata"}:
            if sources:
                return None
            if target == "notebook":
                statements.extend(
                    [
                        "source_paths = globals().get('source_paths', {})",
                        f"{name}_Path = source_paths.get({node.id!r})",
                        f"if not {name}_Path: raise ValueError("
                        f'"Configure source_paths[{node.id!r}] before running")',
                        f"{name} = spark.read.option('header', True)."
                        f"option('inferSchema', True).csv({name}_Path)",
                    ]
                )
            else:
                statements.append(
                    f"    {name} = Record.Field(SourceBindings, {_m_string(node.id)})"
                )
            references[node.id] = name
            required_bindings.append(
                f"source_paths[{node.id!r}]"
                if target == "notebook"
                else f"source_queries[{node.id!r}]"
            )
        elif operation == "formula":
            if len(sources) != 1:
                return None
            formulas = fromstring(node.configuration.get("FormulaFields", "<FormulaFields/>"))
            if not list(formulas):
                return None
            current = sources[0]
            for formula_index, formula in enumerate(formulas, start=1):
                field = formula.get("field", "")
                translated = _translate_expression(formula.get("expression", ""), target)
                if not field or translated is None:
                    return None
                step = (
                    name
                    if len(formulas) == 1
                    else _unique_step_name(
                        f"{name}_{formula_index}", used_step_names, node.id
                    )
                )
                if target == "notebook":
                    statements.append(
                        f"{step} = {current}.withColumn({json.dumps(field)}, {translated})"
                    )
                else:
                    statements.append(
                        f"    {step} = Table.AddColumn("
                        f"{current}, {_m_string(field)}, each {translated})"
                    )
                current = step
            references[node.id] = current
            sort_fields[node.id] = sort_fields.get(source_ids[0], [])
        elif operation in {"select", "alteryxselect"}:
            if len(sources) != 1:
                return None
            select_fields = fromstring(
                node.configuration.get("SelectFields", "<SelectFields/>")
            )
            if any(
                set(field.attrib) - {"field", "selected"}
                or field.get("selected") not in {"True", "False"}
                or (
                    field.get("field", "").startswith("*")
                    and field.get("field") != "*Unknown"
                )
                for field in select_fields
            ):
                return None
            selected = [
                field.get("field", "")
                for field in select_fields
                if field.get("selected") == "True"
                and field.get("field") not in {"*Unknown", ""}
            ]
            wildcard = any(
                field.get("field") == "*Unknown" and field.get("selected") == "True"
                for field in select_fields
            )
            if wildcard:
                if target == "notebook":
                    statements.append(f"{name} = {sources[0]}")
                references[node.id] = sources[0]
            elif selected:
                if target == "notebook":
                    statements.append(
                        f"{name} = {sources[0]}.select(*{json.dumps(selected)})"
                    )
                else:
                    columns = ", ".join(_m_string(field) for field in selected)
                    statements.append(
                        f"    {name} = Table.SelectColumns({sources[0]}, {{{columns}}})"
                    )
                references[node.id] = name
            else:
                return None
            sort_fields[node.id] = sort_fields.get(source_ids[0], [])
        elif operation == "filter":
            if len(sources) != 1:
                return None
            translated = _translate_expression(_filter_expression(node), target)
            if translated is None:
                return None
            if target == "notebook":
                statements.append(f"{name} = {sources[0]}.filter({translated})")
            else:
                statements.append(
                    f"    {name} = Table.SelectRows({sources[0]}, each {translated})"
                )
            references[node.id] = name
            sort_fields[node.id] = sort_fields.get(source_ids[0], [])
        elif operation == "unique":
            if len(sources) != 1:
                return None
            unique_fields = [
                field.get("field", "")
                for field in fromstring(
                    node.configuration.get("UniqueFields", "<UniqueFields/>")
                )
            ]
            if not unique_fields or any(not field for field in unique_fields):
                return None
            if target == "notebook":
                statements.append(
                    f"{name} = {sources[0]}.dropDuplicates({json.dumps(unique_fields)})"
                )
            else:
                unique_columns = ", ".join(
                    _m_string(field) for field in unique_fields
                )
                statements.append(
                    f"    {name} = Table.Distinct("
                    f"{sources[0]}, {{{unique_columns}}})"
                )
            references[node.id] = name
        elif operation == "recordid":
            if len(sources) != 1:
                return None
            field = _text(node, "FieldName")
            start = _int_text(node, "StartValue")
            if not field or start is None:
                return None
            if target == "notebook":
                statements.append(
                    f"{name} = {sources[0]}.withColumn("
                    f"{json.dumps(field)}, F.monotonically_increasing_id() + {start})"
                )
            else:
                statements.append(
                    f"    {name} = Table.AddIndexColumn("
                    f"{sources[0]}, {_m_string(field)}, {start}, 1, Int64.Type)"
                )
            references[node.id] = name
        elif operation == "sample":
            if len(sources) != 1:
                return None
            count = _int_text(node, "N")
            if _text(node, "Mode") != "First" or count is None:
                return None
            statements.append(
                f"{name} = {sources[0]}.limit({count})"
                if target == "notebook"
                else f"    {name} = Table.FirstN({sources[0]}, {count})"
            )
            references[node.id] = name
        elif operation == "datetime":
            if len(sources) != 1:
                return None
            source_field = _text(node, "InputFieldName")
            output_field = _text(node, "OutputFieldName")
            format_string = _text(node, "Format")
            if (
                _text(node, "IsFrom").casefold() != "true"
                or not source_field
                or not output_field
                or not format_string
            ):
                return None
            if target == "notebook":
                statements.append(
                    f"{name} = {sources[0]}.withColumn("
                    f"{json.dumps(output_field)}, "
                    f"F.to_date(F.col({json.dumps(source_field)}), "
                    f"{json.dumps(format_string)}))"
                )
            else:
                statements.append(
                    f"    {name} = Table.AddColumn("
                    f"{sources[0]}, {_m_string(output_field)}, each "
                    f"Date.FromText(Text.From(Record.Field(_, "
                    f"{_m_string(source_field)})), "
                    f"[Format = {_m_string(format_string)}]), type date)"
                )
            references[node.id] = name
        elif operation == "regex":
            if len(sources) != 1:
                return None
            source_field = _text(node, "Field")
            pattern = _text(node, "RegExExpression")
            outputs = [
                field.get("field", "")
                for field in fromstring(
                    node.configuration.get("ParseComplex", "<ParseComplex/>")
                )
            ]
            if (
                _text(node, "Method") != "ParseComplex"
                or not source_field
                or not pattern
                or not outputs
                or any(not output for output in outputs)
            ):
                return None
            case_insensitive = _text(node, "CaseInsensitve").casefold() == "true"
            if case_insensitive:
                pattern = "(?i)" + pattern
            current = sources[0]
            if target == "notebook":
                for group, output in enumerate(outputs, start=1):
                    step = name if group == len(outputs) else f"{name}_{group}"
                    statements.append(
                        f"{step} = {current}.withColumn("
                        f"{json.dumps(output)}, "
                        f"F.regexp_extract(F.col({json.dumps(source_field)}), "
                        f"{json.dumps(pattern)}, {group}))"
                    )
                    current = step
            elif pattern.removeprefix("(?i)") == "([A-Z]+)-([0-9]+)" and len(outputs) == 2:
                source_value = (
                    f"Text.Upper(Text.From(Record.Field(_, {_m_string(source_field)})))"
                    if case_insensitive
                    else f"Text.From(Record.Field(_, {_m_string(source_field)}))"
                )
                first_step = _unique_step_name(f"{name}_1", used_step_names, node.id)
                statements.extend(
                    [
                        f"    {first_step} = Table.AddColumn("
                        f"{current}, {_m_string(outputs[0])}, each "
                        f"Text.BeforeDelimiter({source_value}, {_m_string('-')}), "
                        "type text)",
                        f"    {name} = Table.AddColumn("
                        f"{first_step}, {_m_string(outputs[1])}, each "
                        f"Text.AfterDelimiter({source_value}, {_m_string('-')}), "
                        "type text)",
                    ]
                )
                current = name
            else:
                return None
            references[node.id] = current
        elif operation == "sort":
            if len(sources) != 1:
                return None
            specs = [
                (field.get("field", ""), field.get("order", "Ascending"))
                for field in fromstring(node.configuration.get("SortInfo", "<SortInfo/>"))
            ]
            if not specs or any(not field for field, _ in specs):
                return None
            if target == "notebook":
                expressions = ", ".join(
                    f"F.col({json.dumps(field)})."
                    f"{'desc' if order.casefold() == 'descending' else 'asc'}()"
                    for field, order in specs
                )
                statements.append(f"{name} = {sources[0]}.orderBy({expressions})")
            else:
                values = ", ".join(
                    "{" + f"{_m_string(field)}, Order."
                    f"{'Descending' if order.casefold() == 'descending' else 'Ascending'}" + "}"
                    for field, order in specs
                )
                statements.append(f"    {name} = Table.Sort({sources[0]}, {{{values}}})")
            references[node.id] = name
            sort_fields[node.id] = specs
        elif operation == "multirowformula":
            if len(sources) != 1:
                return None
            output_field = _text(node, "CreateField_Name")
            expression = html.unescape(html.unescape(_text(node, "Expression")))
            group_fields = [
                field.get("field", "")
                for field in fromstring(
                    node.configuration.get("GroupByFields", "<GroupByFields/>")
                )
            ]
            match = re.fullmatch(
                rf"\[Row-1:{re.escape(output_field)}\]\s*\+\s*\[([^\]]+)\]",
                expression,
            )
            ordering = sort_fields.get(source_ids[0], [])
            if (
                not output_field
                or not match
                or not group_fields
                or any(not field for field in group_fields)
                or not ordering
            ):
                return None
            if target == "notebook":
                order_expressions = ", ".join(
                    f"F.col({json.dumps(field)})."
                    f"{'desc' if order.casefold() == 'descending' else 'asc'}()"
                    for field, order in ordering
                )
                window = (
                    f"Window.partitionBy(*{json.dumps(group_fields)})."
                    f"orderBy({order_expressions})."
                    "rowsBetween(Window.unboundedPreceding, Window.currentRow)"
                )
                statements.append(
                    f"{name} = {sources[0]}.withColumn("
                    f"{json.dumps(output_field)}, "
                    f"F.sum(F.col({json.dumps(match.group(1))}).cast('double')).over({window}))"
                )
            else:
                grouped = _unique_step_name(f"{name}_Grouped", used_step_names, node.id)
                grouped_columns = ", ".join(
                    _m_string(field) for field in group_fields
                )
                value_field = _m_string(match.group(1))
                row_index = _m_string("__row_index")
                rows_field = _m_string("__rows")
                statements.extend(
                    [
                        f"    {grouped} = Table.Group("
                        f"{sources[0]}, {{{grouped_columns}}}, "
                        "{{"
                        f"{{{rows_field}, (groupTable) => let "
                        f"Indexed = Table.AddIndexColumn(groupTable, {row_index}, "
                        "0, 1, Int64.Type), "
                        f"Running = Table.AddColumn(Indexed, {_m_string(output_field)}, "
                        f"each List.Sum(List.FirstN(Table.Column(Indexed, {value_field}), "
                        f"Record.Field(_, {row_index}) + 1)), type number) "
                        f"in Table.RemoveColumns(Running, {{{row_index}}}), type table}}"
                        "}})",
                        f"    {name} = Table.Combine(Table.Column({grouped}, {rows_field}))",
                    ]
                )
            references[node.id] = name
            sort_fields[node.id] = ordering
        elif operation == "summarize":
            if len(sources) != 1:
                return None
            summary_fields = list(
                fromstring(
                    node.configuration.get("SummarizeFields", "<SummarizeFields/>")
                )
            )
            groups = [
                field.get("field", "")
                for field in summary_fields
                if field.get("action") == "GroupBy"
            ]
            aggregations = [
                (
                    field.get("action", ""),
                    field.get("field", ""),
                    field.get("rename", ""),
                )
                for field in summary_fields
                if field.get("action") != "GroupBy"
            ]
            if (
                not groups
                or any(not field for field in groups)
                or not aggregations
                or any(
                    action not in {"Sum", "Count"} or not field or not rename
                    for action, field, rename in aggregations
                )
            ):
                return None
            if target == "notebook":
                values = ", ".join(
                    (
                        f"F.sum(F.col({json.dumps(field)}).cast('double'))"
                        if action == "Sum"
                        else f"F.count(F.col({json.dumps(field)}))"
                    )
                    + f".alias({json.dumps(rename)})"
                    for action, field, rename in aggregations
                )
                statements.append(
                    f"{name} = {sources[0]}.groupBy(*{json.dumps(groups)}).agg({values})"
                )
            else:
                values = ", ".join(
                    "{"
                    + f"{_m_string(rename)}, each "
                    + (
                        f"List.Sum(List.Transform([{field}], Number.From))"
                        if action == "Sum"
                        else "Table.RowCount(_)"
                    )
                    + ", type number}"
                    for action, field, rename in aggregations
                )
                statements.append(
                    f"    {name} = Table.Group("
                    f"{sources[0]}, "
                    f"{{{', '.join(_m_string(field) for field in groups)}}}, "
                    f"{{{values}}})"
                )
            references[node.id] = name
        elif operation == "join":
            if len(sources) != 2:
                return None
            join_info = fromstring(
                node.configuration.get("JoinInfo", "<Repeated/>")
            )
            key_sets = [
                [field.get("field", "") for field in info]
                for info in list(join_info)
            ]
            join_mode = _text(node, "JoinMode").casefold()
            outgoing_anchors = {
                anchor.casefold()
                for src, _, anchor in edges
                if src == node.id and anchor
            }
            is_inner_join = join_mode == "inner" or (
                not join_mode and (not outgoing_anchors or outgoing_anchors == {"join"})
            )
            if (
                not is_inner_join
                or len(key_sets) != 2
                or any(not keys or any(not key for key in keys) for keys in key_sets)
                or len(key_sets[0]) != len(key_sets[1])
            ):
                return None
            if target == "notebook":
                conditions = " & ".join(
                    f"({sources[0]}[{json.dumps(left)}] == "
                    f"{sources[1]}[{json.dumps(right)}])"
                    for left, right in zip(key_sets[0], key_sets[1], strict=True)
                )
                drops = "".join(
                    f".drop({sources[1]}[{json.dumps(right)}])" for right in key_sets[1]
                )
                statements.append(
                    f"{name} = {sources[0]}.join("
                    f"{sources[1]}, {conditions}, 'inner'){drops}"
                )
            else:
                left_keys = ", ".join(_m_string(field) for field in key_sets[0])
                right_keys = ", ".join(_m_string(field) for field in key_sets[1])
                joined = _unique_step_name(f"{name}_Joined", used_step_names, node.id)
                right_columns = _unique_step_name(
                    f"{name}_RightColumns", used_step_names, node.id
                )
                output_columns = _unique_step_name(
                    f"{name}_OutputColumns", used_step_names, node.id
                )
                statements.extend(
                    [
                        f"    {joined} = Table.NestedJoin("
                        f"{sources[0]}, {{{left_keys}}}, {sources[1]}, "
                        f"{{{right_keys}}}, {_m_string('__right')}, JoinKind.Inner)",
                        f"    {right_columns} = List.RemoveItems("
                        f"Table.ColumnNames({sources[1]}), {{{right_keys}}})",
                        f"    {output_columns} = List.Transform("
                        f"{right_columns}, each if List.Contains("
                        f"Table.ColumnNames({sources[0]}), _) then _ & "
                        f"{_m_string('_Right')} else _)",
                        f"    {name} = Table.ExpandTableColumn("
                        f"{joined}, {_m_string('__right')}, "
                        f"{right_columns}, {output_columns})",
                    ]
                )
            references[node.id] = name
        elif operation == "appendfields":
            if target != "notebook" or len(sources) != 2:
                return None
            statements.append(f"{name} = {sources[0]}.crossJoin({sources[1]})")
            references[node.id] = name
        elif operation == "transpose":
            if target != "notebook" or len(sources) != 1:
                return None
            key_fields = [
                field.get("field", "")
                for field in fromstring(
                    node.configuration.get("KeyFields", "<KeyFields/>")
                )
                if field.get("selected") == "True"
            ]
            data_fields = [
                field.get("field", "")
                for field in fromstring(
                    node.configuration.get("DataFields", "<DataFields/>")
                )
                if field.get("selected") == "True"
            ]
            if not key_fields or not data_fields:
                return None
            statements.append(
                f"{name} = {sources[0]}.unpivot("
                f"{json.dumps(key_fields)}, {json.dumps(data_fields)}, "
                '"Name", "Value")'
            )
            references[node.id] = name
        elif operation == "union":
            if len(sources) < 2 or _text(node, "Mode").casefold() != "byname":
                return None
            if target == "notebook":
                expression = sources[0]
                for source in sources[1:]:
                    expression += f".unionByName({source}, allowMissingColumns=True)"
                statements.append(f"{name} = {expression}")
            else:
                statements.append(f"    {name} = Table.Combine({{{', '.join(sources)}}})")
            references[node.id] = name
        elif operation == "crosstab":
            if len(sources) != 1:
                return None
            group_fields = [
                field.get("field", "")
                for field in fromstring(
                    node.configuration.get("GroupFields", "<GroupFields/>")
                )
            ]
            header_field = _field_text(node, "HeaderField")
            data_field = _field_text(node, "DataField")
            methods = [
                method.get("method", "")
                for method in fromstring(node.configuration.get("Methods", "<Methods/>"))
            ]
            if (
                not group_fields
                or any(not field for field in group_fields)
                or not header_field
                or not data_field
                or methods != ["Sum"]
            ):
                return None
            if target == "notebook":
                statements.append(
                    f"{name} = {sources[0]}.groupBy(*{json.dumps(group_fields)})."
                    f"pivot({json.dumps(header_field)})."
                    f"agg(F.sum(F.col({json.dumps(data_field)}).cast('double')))"
                )
            else:
                selected = [*group_fields, header_field, data_field]
                columns = ", ".join(_m_string(field) for field in selected)
                source_step = _unique_step_name(
                    f"{name}_Source", used_step_names, node.id
                )
                statements.extend(
                    [
                        f"    {source_step} = Table.SelectColumns("
                        f"{sources[0]}, {{{columns}}})",
                        f"    {name} = Table.Pivot("
                        f"{source_step}, "
                        f"List.Distinct(Table.Column({source_step}, "
                        f"{_m_string(header_field)})), "
                        f"{_m_string(header_field)}, {_m_string(data_field)}, "
                        "each List.Sum(List.Transform(_, Number.From)))",
                    ]
                )
            references[node.id] = name
        elif operation in {"autofield", "outputdata", "dbfileoutput", "browse"}:
            if len(sources) != 1:
                return None
            references[node.id] = sources[0]
            if len(source_ids) == 1:
                sort_fields[node.id] = sort_fields.get(source_ids[0], [])
        if target == "dataflow":
            node_steps[node.id] = statements[statement_start:]
            node_results[node.id] = references[node.id]
            if node.id not in merged_into:
                references[node.id] = name
    if any(terminal not in references for terminal in terminals):
        return None
    if target == "notebook":
        displays = "\n".join(f"display({references[terminal]})" for terminal in terminals)
        imports = "from pyspark.sql import Window, functions as F"
        code = (
            imports + "\n\n" + "\n".join(statements) + f"\n\n{displays}\n"
        )
        return DagCompilation(code, required_bindings, [], [], [], {})
    loaded_outputs = [
        (variable_names[terminal], references[terminal])
        for terminal in terminals
        if by_id[terminal].name.casefold() in output_operations
    ]
    explicit_destinations = bool(loaded_outputs)
    if not loaded_outputs:
        loaded_outputs = [
            (variable_names[terminal], references[terminal]) for terminal in terminals
        ]
    loaded_queries = [query_name for query_name, _ in loaded_outputs]
    source_bindings_required = any(
        binding.startswith("source_queries[") for binding in required_bindings
    )
    if explicit_destinations:
        required_bindings.extend(
            f"destinations[{query_name!r}]" for query_name in loaded_queries
        )
    anchor_steps: dict[str, list[str]] = {
        node.id: [] for node in ordered if node.id not in merged_into
    }
    for node in ordered:
        anchor_id = node.id
        while anchor_id in merged_into:
            anchor_id = merged_into[anchor_id]
        anchor_steps[anchor_id].extend(node_steps[node.id])

    query_lines = ["section Section1;"]
    definition_queries: list[str] = []
    if source_bindings_required:
        query_lines.extend(
            [
                "",
                'shared SourceBindings = error "Configure source bindings before refresh";',
            ]
        )
        definition_queries.append("SourceBindings")
    kept_queries: set[str] = set()
    for node in ordered:
        if node.id in merged_into:
            continue
        query_name = variable_names[node.id]
        kept_queries.add(query_name)
        query_lines.extend(
            [
                "",
                _m_shared_query(
                    query_name,
                    anchor_steps[node.id],
                    node_results[node.id],
                ),
            ]
        )
        definition_queries.append(query_name)
    query_group_assignments = {
        query_name: group_id
        for query_name, group_id in all_assignments.items()
        if query_name in kept_queries
    }
    return DagCompilation(
        "\n".join(query_lines) + "\n",
        required_bindings,
        definition_queries,
        loaded_queries,
        query_groups,
        query_group_assignments,
    )


def _unique_step_name(base: str, used: set[str], node_id: str) -> str:
    candidate = base if base not in used else f"{base}_{node_id}"
    while candidate in used:
        candidate = f"{candidate}_s"
    used.add(candidate)
    return candidate


def _m_shared_query(query_name: str, steps: list[str], result: str) -> str:
    if not steps:
        return f"shared {query_name} = {result};"
    formatted = ",\n".join(
        "    " + step.strip().replace("\n", "\n    ")
        for step in steps
    )
    return f"shared {query_name} = let\n{formatted}\nin\n    {result};"


def _dataflow_query_groups(
    all_nodes: tuple[GraphNode, ...],
    query_names: dict[str, str],
    source_sha256: str,
) -> tuple[list[DataflowQueryGroup], dict[str, str]]:
    containers = [
        node
        for node in all_nodes
        if node.name.casefold() == "toolcontainer"
        and node.x is not None
        and node.y is not None
        and node.width is not None
        and node.height is not None
    ]
    group_ids = {
        container.id: str(
            uuid.uuid5(
                uuid.NAMESPACE_URL,
                f"query-group:{source_sha256}:{container.id}",
            )
        )
        for container in containers
    }
    nodes_by_id = {node.id: node for node in all_nodes}
    groups: list[DataflowQueryGroup] = []
    for order, container in enumerate(containers):
        parents = [
            candidate
            for candidate in containers
            if candidate.id != container.id
            and _container_area(candidate) > _container_area(container)
            and _container_contains_container(candidate, container)
        ]
        parent = min(parents, key=_container_area, default=None)
        groups.append(
            DataflowQueryGroup(
                id=group_ids[container.id],
                name=(container.label or f"Container {container.id}")[:256],
                description=f"Migrated from Alteryx ToolContainer {container.id}",
                parent_id=group_ids[parent.id] if parent is not None else None,
                order=order,
            )
        )
    assignments: dict[str, str] = {}
    for node_id, query_name in query_names.items():
        node = nodes_by_id[node_id]
        members = [
            container
            for container in containers
            if node.x is not None
            and node.y is not None
            and _container_contains_point(container, node.x, node.y)
        ]
        if members:
            assignments[query_name] = group_ids[min(members, key=_container_area).id]
    return groups, assignments


def _container_area(node: GraphNode) -> float:
    if node.width is None or node.height is None:
        return float("inf")
    return node.width * node.height


def _container_contains_point(container: GraphNode, x: float, y: float) -> bool:
    if (
        container.x is None
        or container.y is None
        or container.width is None
        or container.height is None
    ):
        return False
    return (
        container.x <= x <= container.x + container.width
        and container.y <= y <= container.y + container.height
    )


def _container_contains_container(parent: GraphNode, child: GraphNode) -> bool:
    if (
        child.x is None
        or child.y is None
        or child.width is None
        or child.height is None
    ):
        return False
    return _container_contains_point(parent, child.x, child.y) and _container_contains_point(
        parent,
        child.x + child.width,
        child.y + child.height,
    )


def _python_variable(value: str) -> str:
    normalized = re.sub(r"[^A-Za-z0-9]+", "_", value).strip("_").casefold()
    if not normalized:
        return "stage"
    if normalized[0].isdigit():
        return f"stage_{normalized}"
    return normalized


def _text(node: GraphNode, key: str) -> str:
    element = fromstring(node.configuration.get(key, f"<{key}/>"))
    return (element.text or element.get("value", "") or "").strip()


def _field_text(node: GraphNode, key: str) -> str:
    element = fromstring(node.configuration.get(key, f"<{key}/>"))
    return (element.get("field", "") or element.text or "").strip()


def _int_text(node: GraphNode, key: str) -> int | None:
    value = _text(node, key)
    return int(value) if re.fullmatch(r"-?\d+", value) else None


def _text_input(
    node: GraphNode, diagnostics: list[str]
) -> tuple[list[str], list[list[str | None]]]:
    fields = fromstring(node.configuration.get("Fields", "<Fields/>"))
    names = [field.get("name", "") for field in fields]
    data = fromstring(node.configuration.get("Data", "<Data/>"))
    rows = [[(cell.text if cell.text is not None else None) for cell in row] for row in data]
    if not names or any(not name for name in names):
        diagnostics.append(f"Tool {node.id}: TextInput fields are invalid")
    if any(len(row) != len(names) for row in rows):
        diagnostics.append(f"Tool {node.id}: TextInput row width does not match fields")
    return names, rows


def _filter_expression(node: GraphNode) -> str:
    mode = _text(node, "Mode")
    expression = _text(node, "Expression")
    if mode != "Simple":
        return expression
    simple = fromstring(node.configuration.get("Simple", "<Simple/>"))
    field = simple.findtext("Field", default="")
    operator = simple.findtext("Operator", default="")
    operand = simple.findtext("Operands/Operand", default="")
    if not field or not operator:
        return ""
    escaped = operand.replace("\\", "\\\\").replace('"', '\\"')
    return f'[{field}] {operator} "{escaped}"'


def _translate_expression(expression: str, target: Target) -> str | None:
    expression = html.unescape(html.unescape(expression.strip()))
    numeric = re.fullmatch(r"-?\d+(?:\.\d+)?", expression)
    if numeric:
        return (
            f"F.lit({numeric.group(0)})"
            if target == "notebook"
            else numeric.group(0)
        )
    literal = re.fullmatch(r'"([^"\r\n]*)"', expression)
    if literal:
        value = literal.group(1)
        return (
            f"F.lit({json.dumps(value)})"
            if target == "notebook"
            else _m_string(value)
        )
    if expression.upper().startswith("IIF(") and expression.endswith(")"):
        arguments = _split_expression_arguments(expression[4:-1])
        if len(arguments) == 3:
            condition = _translate_expression(arguments[0], target)
            true_value = _translate_expression(arguments[1], target)
            false_value = _translate_expression(arguments[2], target)
            if condition and true_value and false_value:
                if target == "notebook":
                    return (
                        f"F.when({condition}, {true_value})."
                        f"otherwise({false_value})"
                    )
                return (
                    f"if {condition} then {true_value} else {false_value}"
                )
    null_or = re.fullmatch(
        r"IsNull\(\[([^\]]+)\]\)\s+OR\s+(.+)",
        expression,
        re.IGNORECASE,
    )
    if null_or:
        field, remainder = null_or.groups()
        translated = _translate_expression(remainder, target)
        if translated is None:
            return None
        if target == "notebook":
            return f"F.col({json.dumps(field)}).isNull() | ({translated})"
        return (
            f"Record.Field(_, {_m_string(field)}) = null or ({translated})"
        )
    uppercase = re.fullmatch(r"Uppercase\(\[([^\]]+)\]\)", expression, re.IGNORECASE)
    if uppercase:
        field = uppercase.group(1)
        return (
            f"F.upper(F.col({json.dumps(field)}))"
            if target == "notebook"
            else f"Text.Upper(Text.From(Record.Field(_, {_m_string(field)})))"
        )
    concatenation = re.fullmatch(
        r'\[([^\]]+)\]\s*\+\s*"([^"]*)"\s*\+\s*\[([^\]]+)\]'
        r'\s*\+\s*"([^"]*)"\s*\+\s*\[([^\]]+)\]',
        expression,
    )
    if concatenation:
        first, separator_one, second, separator_two, third = concatenation.groups()
        if separator_one != separator_two:
            return None
        if target == "notebook":
            return (
                f"F.concat_ws({json.dumps(separator_one)}, "
                f"F.col({json.dumps(first)}), F.col({json.dumps(second)}), "
                f"F.col({json.dumps(third)}))"
            )
        return (
            f"Text.Combine({{Text.From(Record.Field(_, {_m_string(first)})), "
            f"Text.From(Record.Field(_, {_m_string(second)})), "
            f"Text.From(Record.Field(_, {_m_string(third)}))}}, "
            f"{_m_string(separator_one)})"
        )
    converted_arithmetic = re.fullmatch(
        r"ToNumber\(\[([^\]]+)\]\)\s*([+\-*/])\s*"
        r"ToNumber\(\[([^\]]+)\]\)",
        expression,
        re.IGNORECASE,
    )
    if converted_arithmetic:
        left, operator, right = converted_arithmetic.groups()
        if target == "notebook":
            return (
                f"F.col({json.dumps(left)}).cast('double') {operator} "
                f"F.col({json.dumps(right)}).cast('double')"
            )
        return (
            f"Number.From(Record.Field(_, {_m_string(left)})) {operator} "
            f"Number.From(Record.Field(_, {_m_string(right)}))"
        )
    tax_arithmetic = re.fullmatch(
        r"\[([^\]]+)\]\s*\*\s*\(1\s*\+\s*ToNumber\(\[([^\]]+)\]\)\)",
        expression,
        re.IGNORECASE,
    )
    if tax_arithmetic:
        amount_field, rate_field = tax_arithmetic.groups()
        if target == "notebook":
            return (
                f"F.col({json.dumps(amount_field)}) * "
                f"(F.lit(1) + F.col({json.dumps(rate_field)}).cast('double'))"
            )
        return (
            f"Record.Field(_, {_m_string(amount_field)}) * "
            f"(1 + Number.From(Record.Field(_, {_m_string(rate_field)})))"
        )
    converted_comparison = re.fullmatch(
        r"ToNumber\(\[([^\]]+)\]\)\s*(>=|<=|!=|=|>|<)\s*"
        r"(-?\d+(?:\.\d+)?)",
        expression,
        re.IGNORECASE,
    )
    if converted_comparison:
        field, operator, value = converted_comparison.groups()
        if target == "notebook":
            operator = "==" if operator == "=" else operator
            return f"F.col({json.dumps(field)}).cast('double') {operator} {value}"
        operator = "<>" if operator == "!=" else operator
        return f"Number.From(Record.Field(_, {_m_string(field)})) {operator} {value}"
    conditional = re.fullmatch(
        r'IIF\((\[[^\]\r\n]+\]\s*(?:>=|<=|!=|=|>|<)\s*-?\d+(?:\.\d+)?),\s*'
        r'"([^"\r\n]*)",\s*"([^"\r\n]*)"\)',
        expression,
        re.IGNORECASE,
    )
    if conditional:
        condition, true_value, false_value = conditional.groups()
        translated_condition = _translate_expression(condition, target)
        if translated_condition is None:
            return None
        if target == "notebook":
            return (
                f"F.when({translated_condition}, F.lit({json.dumps(true_value)}))."
                f"otherwise(F.lit({json.dumps(false_value)}))"
            )
        return (
            f"if {translated_condition} then {_m_string(true_value)} "
            f"else {_m_string(false_value)}"
        )
    field_arithmetic = re.fullmatch(
        r"\[([^\]\r\n]+)\]\s*([+\-*/])\s*\[([^\]\r\n]+)\]",
        expression,
    )
    if field_arithmetic:
        left, operator, right = field_arithmetic.groups()
        if target == "notebook":
            return (
                f"F.col({json.dumps(left)}) {operator} F.col({json.dumps(right)})"
            )
        return (
            f"Record.Field(_, {_m_string(left)}) {operator} "
            f"Record.Field(_, {_m_string(right)})"
        )
    comparison = re.fullmatch(
        r'\[([^\]\r\n]+)\]\s*(>=|<=|!=|=|>|<)\s*(?:"([^"\r\n]*)"|(-?\d+(?:\.\d+)?))',
        expression,
    )
    if comparison:
        field, operator, text, number = comparison.groups()
        if len(field) > 256:
            return None
        if target == "notebook":
            operator = "==" if operator == "=" else operator
            value = json.dumps(text) if text is not None else number
            return f"F.col({json.dumps(field)}) {operator} {value}"
        operator = "<>" if operator == "!=" else operator
        value = _m_string(text) if text is not None else number
        return f"Record.Field(_, {_m_string(field)}) {operator} {value}"
    formula = re.fullmatch(
        r"(ToNumber\()?(\[[^\]\r\n]+\])\)?(?:\s*([+\-*/])\s*(-?\d+(?:\.\d+)?))?",
        expression,
        re.IGNORECASE,
    )
    if formula:
        conversion, reference, operator, number = formula.groups()
        field = reference[1:-1]
        if target == "notebook":
            value = f"F.col({json.dumps(field)})"
            if conversion:
                value = f"{value}.cast('double')"
        else:
            value = f"Record.Field(_, {_m_string(field)})"
            if conversion:
                value = f"Number.From({value})"
        return f"{value} {operator} {number}" if operator and number else value
    return None


def _split_expression_arguments(value: str) -> list[str]:
    arguments: list[str] = []
    start = 0
    depth = 0
    quoted = False
    for index, character in enumerate(value):
        if character == '"':
            quoted = not quoted
        elif not quoted and character == "(":
            depth += 1
        elif not quoted and character == ")":
            depth -= 1
        elif not quoted and character == "," and depth == 0:
            arguments.append(value[start:index].strip())
            start = index + 1
    arguments.append(value[start:].strip())
    return arguments


def _m_value(value: str | None) -> str:
    if value is None:
        return "null"
    return _m_string(value)


def _m_string(value: str) -> str:
    return (
        '"'
        + value.replace("#", "#(#)")
        .replace('"', '""')
        .replace("\r", "#(cr)")
        .replace("\n", "#(lf)")
        + '"'
    )


def _linear_nodes(
    nodes: tuple[GraphNode, ...], edges: tuple[tuple[str, str, str], ...]
) -> list[GraphNode]:
    if not nodes or len(edges) != len(nodes) - 1:
        return []
    by_id = {node.id: node for node in nodes}
    if any(source not in by_id or target not in by_id for source, target, _ in edges):
        return []
    incoming = {target for _, target, _ in edges}
    roots = [node for node in nodes if node.id not in incoming]
    if len(roots) != 1:
        return []
    output: list[GraphNode] = []
    node = roots[0]
    while node not in output:
        output.append(node)
        outgoing = [(target, anchor) for source, target, anchor in edges if source == node.id]
        if not outgoing:
            break
        if len(outgoing) != 1 or outgoing[0][1] == "False":
            return []
        node = by_id[outgoing[0][0]]
    return output if len(output) == len(nodes) else []
