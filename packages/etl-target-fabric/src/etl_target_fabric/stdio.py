"""Stateless single-shot CLI and JSON bridge for Fabric codegen and dry-run."""

from __future__ import annotations

import argparse
import json
import sys
from collections.abc import Sequence
from pathlib import Path

from etl_migration_core.sources.defaults import create_default_registry
from etl_target_fabric.assessment.evaluator import evaluate_etl_native_route
from etl_target_fabric.compilers.alteryx import Target, generate_candidate
from etl_target_fabric.compilers.ir import compile_asset


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        prog="etl-fabric",
        description="Stateless Microsoft Fabric compiler & evaluator CLI (JSON output).",
    )
    sub = parser.add_subparsers(dest="command", required=True)

    compile_cmd = sub.add_parser("compile")
    compile_cmd.add_argument("path", type=Path)
    compile_cmd.add_argument(
        "--target",
        choices=("dataflow", "notebook", "pipeline"),
        default="dataflow",
    )

    eval_cmd = sub.add_parser("evaluate")
    eval_cmd.add_argument("path", type=Path)

    args = parser.parse_args(list(argv) if argv is not None else None)
    path: Path = args.path
    registry = create_default_registry()
    detected = registry.detect(path, path.name)
    if args.command == "compile":
        target: Target = args.target
        if detected.match.platform.value == "alteryx" and target in {
            "dataflow",
            "notebook",
        }:
            candidate = generate_candidate(path, target)
            print(candidate.model_dump_json(indent=2))
            return 0
        package = registry.parse(path, detected.match)
        results = [
            {
                "asset_id": compiled.asset_id,
                "name": compiled.name,
                "target": compiled.target,
                "validation_state": compiled.validation_state,
                "deployable": compiled.deployable,
                "runtime_ready": compiled.runtime_ready,
                "diagnostics": list(compiled.diagnostics),
                "required_bindings": list(compiled.required_bindings),
                "code": compiled.code,
            }
            for compiled in (
                compile_asset(package, asset, target) for asset in package.assets
            )
        ]
        print(json.dumps({"assets": results}, indent=2))
        return 0

    package = registry.parse(path, detected.match)
    evaluations = [
        evaluate_etl_native_route(
            package,
            asset,
            base_reason=f"Evaluated {asset.name}",
        ).model_dump(mode="json")
        for asset in package.assets
    ]
    print(json.dumps({"evaluations": evaluations}, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
