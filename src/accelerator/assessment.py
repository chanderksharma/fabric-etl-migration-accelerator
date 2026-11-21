"""Compatibility re-export of Fabric Alteryx assessment from etl-target-fabric."""

from etl_target_fabric.assessment import (
    ANNOTATION_IDENTITIES as ANNOTATION_IDENTITIES,
)
from etl_target_fabric.assessment import (
    DATAFLOW_TOOL_MARKERS as DATAFLOW_TOOL_MARKERS,
)
from etl_target_fabric.assessment import (
    NEUTRAL_TOOL_MARKERS as NEUTRAL_TOOL_MARKERS,
)
from etl_target_fabric.assessment import (
    NOTEBOOK_TOOL_MARKERS as NOTEBOOK_TOOL_MARKERS,
)
from etl_target_fabric.assessment import (
    PIPELINE_TOOL_MARKERS as PIPELINE_TOOL_MARKERS,
)
from etl_target_fabric.assessment import (
    REGISTRY_VERSION as REGISTRY_VERSION,
)
from etl_target_fabric.assessment import (
    RULES_VERSION as RULES_VERSION,
)
from etl_target_fabric.assessment import (
    ToolInventoryItem as ToolInventoryItem,
)
from etl_target_fabric.assessment import (
    WorkflowAssessment as WorkflowAssessment,
)
from etl_target_fabric.assessment import (
    WorkflowParseError as WorkflowParseError,
)
from etl_target_fabric.assessment import (
    assess_workflow as assess_workflow,
)
from etl_target_fabric.assessment import (
    registry_entries as registry_entries,
)
from etl_target_fabric.support_matrix import alteryx_support_for

_support_for = alteryx_support_for
