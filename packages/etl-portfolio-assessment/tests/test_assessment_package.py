"""Standalone tests for the etl-portfolio-assessment PyPI package."""

from __future__ import annotations

import json
from pathlib import Path

from etl_portfolio_assessment.service.application import PortfolioAssessmentApplication
from etl_portfolio_assessment.service.stdio import main as assess_stdio_main


def test_portfolio_assessment_application_and_stdio(
    capsys: object,
) -> None:
    sample_dir = Path(__file__).parents[3] / "alteryx-workflows"
    app = PortfolioAssessmentApplication()

    preview = app.preview(sample_dir)
    assert preview.workflow_count > 0

    estate = app.assess_neutral(sample_dir)
    assert estate.failed_count == 0
    assert estate.workflow_count == preview.workflow_count
    payload = estate.model_dump_json().casefold()
    assert "dataflow gen2" not in payload
    assert "f-sku" not in payload

    evidence = app.inspect_evidence(sample_dir)
    assert len(evidence) == preview.workflow_count

    exit_code = assess_stdio_main(["assess", str(sample_dir)])
    assert exit_code in (0, 1)
    assert assess_stdio_main(["preview", str(sample_dir)]) == 0
    assert assess_stdio_main(["evidence", str(sample_dir)]) == 0
    _ = capsys
    parsed = json.loads(estate.model_dump_json())
    assert parsed["workflow_count"] == preview.workflow_count
