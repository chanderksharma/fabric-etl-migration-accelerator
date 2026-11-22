"""Practical remaining engineering effort after code generation.

Binding increments are integer hundredths, and the binding set is sorted before
it is summed. Float addition over an unordered set changes half-even rounding
when ``PYTHONHASHSEED`` changes.
"""

from __future__ import annotations

from collections.abc import Iterable

MAX_EFFORT_DAYS = 21.0
MIN_EFFORT_DAYS = 0.5


def practical_effort_days(estimate: float) -> float:
    """Round and constrain one workflow's remaining effort estimate."""
    return _clamp_days(round(estimate, 1))


def assessment_effort_days(*, unsupported_component_count: int) -> float:
    """Estimate validation and explicit redesign work not covered by generation."""
    estimate = MIN_EFFORT_DAYS + unsupported_component_count
    return practical_effort_days(estimate)


def remaining_effort_days(*, required_bindings: Iterable[str]) -> float:
    """Estimate binding and validation work left after code generation."""
    hundredths = 15
    for binding in sorted(set(required_bindings)):
        normalized = binding.casefold()
        if "independent semantic parity" in normalized:
            hundredths += 15
        elif normalized.startswith("source_") or normalized.startswith("source_paths"):
            hundredths += 8
        elif normalized.startswith("destination"):
            hundredths += 10
        elif "transform" in normalized or "sql_" in normalized:
            hundredths += 25
        else:
            hundredths += 15
    return _clamp_days(_half_even_tenths(hundredths) / 10)


def _half_even_tenths(hundredths: int) -> int:
    """Round hundredths to the nearest tenth with half-to-even."""
    negative = hundredths < 0
    absolute = -hundredths if negative else hundredths
    tenths, remainder = divmod(absolute, 10)
    if remainder > 5 or (remainder == 5 and tenths % 2 == 1):
        tenths += 1
    return -tenths if negative else tenths


def _clamp_days(days: float) -> float:
    return min(MAX_EFFORT_DAYS, max(MIN_EFFORT_DAYS, days))
