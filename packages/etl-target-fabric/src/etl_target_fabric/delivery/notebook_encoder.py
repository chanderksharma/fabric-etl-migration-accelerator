"""Structured Fabric PySpark notebook cell builder from generated Python source."""

from __future__ import annotations

import ast
import json
import re

from etl_migration_core.contracts.ir import SourcePlatform
from etl_target_fabric.compilers.alteryx import Candidate


def build_notebook_cells(
    candidate: Candidate, display_name: str
) -> list[dict[str, object]]:
    """Split generated PySpark source into documented, tagged Fabric notebook cells."""
    workflow_label = candidate.workflow.replace("`", "\\`")
    statements = _python_statement_blocks(candidate.code)
    imports: list[tuple[ast.stmt, str]] = []
    parameters: list[tuple[ast.stmt, str]] = []
    sources: list[tuple[ast.stmt, str]] = []
    transformations: list[tuple[ast.stmt, str]] = []
    outputs: list[tuple[ast.stmt, str]] = []
    for node, source in statements:
        if isinstance(node, (ast.Import, ast.ImportFrom)) or (
            isinstance(node, ast.FunctionDef)
            and node.name in {"require_transform", "_read_source"}
        ):
            imports.append((node, source))
        elif _is_pipeline_parameter_statement(node, source):
            parameters.append((node, source))
        elif _is_display_statement(node):
            outputs.append((node, source))
        elif not isinstance(node, ast.FunctionDef) and _is_source_statement(source):
            if not source.startswith("source_paths = globals().get("):
                sources.append((node, source))
        else:
            transformations.append((node, source))

    cells = [
        _markdown_cell(
            "\n".join(
                [
                    f"# {display_name}",
                    "",
                    f"Generated from `{workflow_label}` by "
                    f"compiler {candidate.compiler_version}.",
                    "",
                    "## How to use this notebook",
                    "",
                    "1. Review and complete the source configuration.",
                    "2. Run cells from top to bottom.",
                    "3. Inspect the output previews and validate semantic parity.",
                    "",
                    "> **Important:** Generated transformations are unvalidated. "
                    "Confirm schemas, row counts, business rules, and destinations "
                    "before promotion.",
                ]
            )
        )
    ]
    if imports:
        cells.extend(
            [
                _markdown_cell(
                    "## Runtime imports\n\n"
                    "Imports and runtime helpers required by the generated PySpark transformations."
                ),
                _code_cell(_join_statement_blocks(imports), "imports"),
            ]
        )

    if parameters:
        cells.extend(
            [
                _markdown_cell(
                    "## Pipeline parameters\n\n"
                    "Default workflow parameters; overridden when triggered from a "
                    "Fabric Data Pipeline."
                ),
                _code_cell(_join_statement_blocks(parameters), "parameters"),
            ]
        )

    source_keys = _source_binding_keys(candidate.required_bindings)
    if source_keys:
        source_labels = _source_binding_labels(candidate.code)
        table_rows = [
            f"| `{key}` | `{source_labels.get(key, f'Tool {key}')}` |"
            for key in source_keys
        ]
        config_cell = _code_cell(
            "\n".join(
                [
                    "source_paths = {",
                    *[
                        f"    {json.dumps(key)}: \"\",  "
                        f"# {source_labels.get(key, f'Tool {key}')}"
                        for key in source_keys
                    ],
                    "}",
                ]
            ),
            "configuration",
        )
        if not parameters:
            config_cell["metadata"] = {"tags": ["generated", "parameters", "configuration"]}
        cells.extend(
            [
                _markdown_cell(
                    "\n".join(
                        [
                            "## Source configuration",
                            "",
                            "Replace each empty value with an accessible Fabric or "
                            "OneLake path before running the ingestion cells.",
                            "",
                            "| Tool ID | Generated DataFrame |",
                            "| --- | --- |",
                            *table_rows,
                        ]
                    )
                ),
                config_cell,
            ]
        )

    cells.extend(
        _section_cells(
            "Source ingestion",
            "Loads and validates source datasets before transformation.",
            sources,
            chunk_size=12,
            tag="sources",
        )
    )
    source_label = (
        "Alteryx"
        if candidate.source_platform is SourcePlatform.ALTERYX
        else candidate.source_product
    )
    cells.extend(
        _section_cells(
            "Transformations",
            f"Applies the translated {source_label} operations in dependency order.",
            transformations,
            chunk_size=8,
            tag="transformations",
        )
    )
    cells.extend(
        _section_cells(
            "Output preview",
            "Displays terminal DataFrames for review. Replace preview-only output "
            "with approved destination writes after validation.",
            outputs,
            chunk_size=8,
            tag="outputs",
        )
    )
    return cells


def _python_statement_blocks(code: str) -> list[tuple[ast.stmt, str]]:
    lines = code.splitlines()
    tree = ast.parse(code)
    blocks: list[tuple[ast.stmt, str]] = []
    for node in tree.body:
        end = node.end_lineno or node.lineno
        blocks.append((node, "\n".join(lines[node.lineno - 1 : end])))
    return blocks


def _is_display_statement(node: ast.stmt) -> bool:
    return (
        isinstance(node, ast.Expr)
        and isinstance(node.value, ast.Call)
        and isinstance(node.value.func, ast.Name)
        and node.value.func.id == "display"
    )


def _is_pipeline_parameter_statement(node: ast.stmt, source: str) -> bool:
    return (
        isinstance(node, ast.Assign)
        and len(node.targets) == 1
        and isinstance(node.targets[0], ast.Name)
        and "= globals().get(" in source
        and node.targets[0].id not in {"source_paths", "transform_bindings"}
    )


def _is_source_statement(source: str) -> bool:
    return any(
        marker in source
        for marker in (
            "source_paths",
            "_Path",
            "_read_source(",
            "spark.read",
            "spark.createDataFrame",
        )
    )


def _source_binding_keys(bindings: list[str]) -> list[str]:
    keys: list[str] = []
    for binding in bindings:
        match = re.fullmatch(r"""source_paths\[['"]([^'"]+)['"]\]""", binding)
        if match and match.group(1) not in keys:
            keys.append(match.group(1))
    return keys


def _source_binding_labels(code: str) -> dict[str, str]:
    return {
        match.group(2): match.group(1)
        for match in re.finditer(
            r"""(?m)^([A-Za-z_][A-Za-z0-9_]*)_(?:Path|path) = """
            r"""source_paths\.get\(['"]([^'"]+)['"]\)""",
            code,
        )
    }


def _section_cells(
    title: str,
    description: str,
    statements: list[tuple[ast.stmt, str]],
    *,
    chunk_size: int,
    tag: str,
) -> list[dict[str, object]]:
    if not statements:
        return []
    chunks = [
        statements[index : index + chunk_size]
        for index in range(0, len(statements), chunk_size)
    ]
    cells: list[dict[str, object]] = [
        _markdown_cell(f"## {title}\n\n{description}")
    ]
    for index, chunk in enumerate(chunks, start=1):
        names = _assigned_names(chunk)
        label = ", ".join(f"`{name}`" for name in names[:4])
        if len(names) > 4:
            label += f", and {len(names) - 4} more"
        detail = f"\n\nProduces {label}." if label else ""
        cells.extend(
            [
                _markdown_cell(
                    f"### {title} {index} of {len(chunks)}{detail}"
                ),
                _code_cell(_join_statement_blocks(chunk), tag),
            ]
        )
    return cells


def _assigned_names(statements: list[tuple[ast.stmt, str]]) -> list[str]:
    names: list[str] = []
    for node, _ in statements:
        if not isinstance(node, ast.Assign):
            continue
        for target in node.targets:
            if isinstance(target, ast.Name):
                names.append(target.id)
    return names


def _join_statement_blocks(statements: list[tuple[ast.stmt, str]]) -> str:
    return "\n".join(source for _, source in statements)


def _markdown_cell(content: str) -> dict[str, object]:
    return {
        "cell_type": "markdown",
        "metadata": {"tags": ["generated", "documentation"]},
        "source": _notebook_source(content),
    }


def _code_cell(content: str, tag: str) -> dict[str, object]:
    return {
        "cell_type": "code",
        "execution_count": None,
        "metadata": {"tags": ["generated", tag]},
        "outputs": [],
        "source": _notebook_source(content),
    }


def _notebook_source(content: str) -> list[str]:
    return [f"{line}\n" for line in content.splitlines()]
