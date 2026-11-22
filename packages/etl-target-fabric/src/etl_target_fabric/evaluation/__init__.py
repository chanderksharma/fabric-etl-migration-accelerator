"""Compiler-grounded Microsoft Fabric target-fit evaluation.

Portfolio assessment (``etl_target_fabric.assessment``) is static: it never runs a
compiler. This layer sits after it. It may run the compilers to confirm which Fabric
item a workflow can actually produce, and it must not be imported by the assessment
package. ``confirm_assessment`` is the explicit compatibility overlay that applies a
confirmed evaluation to a stored static assessment.
"""

from etl_target_fabric.evaluation.native_route import (
    apply_alteryx_native_route,
    apply_native_route,
    confirm_assessment,
    evaluate_alteryx_native_route,
    evaluate_etl_native_route,
)

__all__ = [
    "apply_alteryx_native_route",
    "apply_native_route",
    "confirm_assessment",
    "evaluate_alteryx_native_route",
    "evaluate_etl_native_route",
]
