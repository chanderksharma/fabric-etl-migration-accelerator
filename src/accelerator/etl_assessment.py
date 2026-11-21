"""Compatibility re-export of Fabric IR assessment from etl-target-fabric."""

from etl_target_fabric.etl_assessment import (
    ASSESSMENT_RULES_VERSION as ASSESSMENT_RULES_VERSION,
)
from etl_target_fabric.etl_assessment import (
    DATAFLOW_OPERATIONS as DATAFLOW_OPERATIONS,
)
from etl_target_fabric.etl_assessment import (
    NEUTRAL_OPERATIONS as NEUTRAL_OPERATIONS,
)
from etl_target_fabric.etl_assessment import (
    NOTEBOOK_OPERATIONS as NOTEBOOK_OPERATIONS,
)
from etl_target_fabric.etl_assessment import (
    PIPELINE_OPERATIONS as PIPELINE_OPERATIONS,
)
from etl_target_fabric.etl_assessment import (
    REGISTRY_VERSIONS as REGISTRY_VERSIONS,
)
from etl_target_fabric.etl_assessment import (
    ComponentInventoryItem as ComponentInventoryItem,
)
from etl_target_fabric.etl_assessment import (
    EtlAssessment as EtlAssessment,
)
from etl_target_fabric.etl_assessment import (
    assess_package as assess_package,
)
from etl_target_fabric.support_matrix import etl_support_for

_support_for = etl_support_for
