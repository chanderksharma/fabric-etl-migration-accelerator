"""Practical remaining engineering effort after Fabric code generation."""

from collections.abc import Iterable

MAX_EFFORT_DAYS = 21.0
MIN_EFFORT_DAYS = 0.5


def practical_effort_days(estimate: float) -> float:
    """Round and constrain one workflow's remaining effort estimate."""
    return min(MAX_EFFORT_DAYS, max(MIN_EFFORT_DAYS, round(estimate, 1)))


def assessment_effort_days(*, unsupported_component_count: int) -> float:
    """Estimate validation and explicit redesign work not covered by generation."""
    estimate = MIN_EFFORT_DAYS + unsupported_component_count
    return practical_effort_days(estimate)


def remaining_effort_days(
    *,
    required_bindings: Iterable[str],
) -> float:
    """Estimate binding and validation work left after code generation."""
    estimate = 0.15
    for binding in set(required_bindings):
        normalized = binding.casefold()
        if "independent semantic parity" in normalized:
            estimate += 0.15
        elif normalized.startswith("source_") or normalized.startswith("source_paths"):
            estimate += 0.08
        elif normalized.startswith("destination"):
            estimate += 0.1
        elif "transform" in normalized or "sql_" in normalized:
            estimate += 0.25
        else:
            estimate += 0.15
    return practical_effort_days(estimate)
