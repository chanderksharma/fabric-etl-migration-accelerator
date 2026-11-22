"""Deprecated import path for Fabric routing, kept for existing consumers.

Compiler-grounded routing moved to ``etl_target_fabric.evaluation`` so that portfolio
assessment stays free of code generation. Names resolve lazily to keep it that way.
"""

from typing import Any

_MOVED = frozenset(
    {
        "apply_alteryx_native_route",
        "apply_native_route",
        "evaluate_alteryx_native_route",
        "evaluate_etl_native_route",
    }
)


def __getattr__(name: str) -> Any:
    if name in _MOVED:
        from etl_target_fabric.evaluation import native_route

        return getattr(native_route, name)
    raise AttributeError(f"module {__name__!r} has no attribute {name!r}")
