"""Tests for practical remaining-effort estimates."""

from accelerator.effort import (
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


def test_effort_is_capped_at_twenty_one_days() -> None:
    assert assessment_effort_days(unsupported_component_count=500) == MAX_EFFORT_DAYS
    assert remaining_effort_days(
        required_bindings=[f"manual_binding_{index}" for index in range(500)],
    ) == MAX_EFFORT_DAYS
