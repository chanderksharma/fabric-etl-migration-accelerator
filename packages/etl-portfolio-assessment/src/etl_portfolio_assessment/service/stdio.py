"""Stateless single-shot CLI and JSON bridge for IDE and CI consumers."""

from __future__ import annotations

import argparse
import json
import sys
from collections.abc import Sequence
from pathlib import Path

from etl_portfolio_assessment.service.application import PortfolioAssessmentApplication


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        prog="etl-assess",
        description="Target-neutral ETL portfolio assessment CLI (stateless JSON output).",
    )
    sub = parser.add_subparsers(dest="command", required=True)
    for name in ("preview", "assess", "evidence"):
        cmd = sub.add_parser(name)
        cmd.add_argument("path", type=Path)

    args = parser.parse_args(list(argv) if argv is not None else None)
    app = PortfolioAssessmentApplication()
    if args.command == "preview":
        print(app.preview(args.path).model_dump_json(indent=2))
        return 0
    if args.command == "assess":
        result = app.assess_neutral(args.path)
        print(result.model_dump_json(indent=2))
        return 1 if result.failed_count else 0
    evidence = [item.model_dump(mode="json") for item in app.inspect_evidence(args.path)]
    print(json.dumps({"workflows": evidence}, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
