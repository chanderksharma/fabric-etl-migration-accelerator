"""Tests for practical remaining-effort estimates."""

import os
import subprocess
import sys

from etl_portfolio_assessment.assessment.effort import (
    MAX_EFFORT_DAYS,
    assessment_effort_days,
    remaining_effort_days,
)


def test_remaining_effort_excludes_generated_build_scope() -> None:
    assert remaining_effort_days(
        required_bindings=["source_path"] * 500,
    ) == 0.5


def test_effort_does_not_apply_delivery_buffer() -> None:
    assert remaining_effort_days(
        required_bindings=["transform_review", "destination_binding"],
    ) == 0.5
    assert assessment_effort_days(unsupported_component_count=1) == 1.5


def test_effort_rounding_is_stable_across_hash_seeds() -> None:
    script = (
        "from etl_migration_core.planning.effort import remaining_effort_days; "
        "print(remaining_effort_days("
        "required_bindings=['destination_table', 'manual_a', 'manual_b']))"
    )
    results = set()
    for seed in ("0", "1"):
        completed = subprocess.run(
            [sys.executable, "-c", script],
            check=True,
            capture_output=True,
            text=True,
            env={**os.environ, "PYTHONHASHSEED": seed},
        )
        results.add(completed.stdout.strip())
    assert results == {"0.6"}


def test_effort_is_capped_at_twenty_one_days() -> None:
    assert assessment_effort_days(unsupported_component_count=500) == MAX_EFFORT_DAYS
    assert remaining_effort_days(
        required_bindings=[f"manual_binding_{index}" for index in range(500)],
    ) == MAX_EFFORT_DAYS
