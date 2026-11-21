"""Compatibility re-export of Fabric capacity model from etl-target-fabric."""

from etl_target_fabric.capacity import (
    CAPACITY_MODEL_VERSION as CAPACITY_MODEL_VERSION,
)
from etl_target_fabric.capacity import (
    COUNT_KEYS as COUNT_KEYS,
)
from etl_target_fabric.capacity import (
    DEFAULT_REFRESH_INTERVAL_MINUTES as DEFAULT_REFRESH_INTERVAL_MINUTES,
)
from etl_target_fabric.capacity import (
    DEFAULT_SOURCE_ROWS_PER_RUN as DEFAULT_SOURCE_ROWS_PER_RUN,
)
from etl_target_fabric.capacity import (
    DEFAULT_SPARK_VCORES as DEFAULT_SPARK_VCORES,
)
from etl_target_fabric.capacity import (
    ELIGIBLE_TARGETS as ELIGIBLE_TARGETS,
)
from etl_target_fabric.capacity import (
    FABRIC_COMPONENTS as FABRIC_COMPONENTS,
)
from etl_target_fabric.capacity import (
    INFORMATICA_COUNT_KEYS as INFORMATICA_COUNT_KEYS,
)
from etl_target_fabric.capacity import (
    INFORMATICA_WEIGHTS as INFORMATICA_WEIGHTS,
)
from etl_target_fabric.capacity import (
    SKU_TIERS as SKU_TIERS,
)
from etl_target_fabric.capacity import (
    SUPPORTED_PLATFORMS as SUPPORTED_PLATFORMS,
)
from etl_target_fabric.capacity import (
    WEIGHTS as WEIGHTS,
)
from etl_target_fabric.capacity import (
    CapacityAssessment as CapacityAssessment,
)
from etl_target_fabric.capacity import (
    CapacityPortfolioEstimate as CapacityPortfolioEstimate,
)
from etl_target_fabric.capacity import (
    CapacityScenario as CapacityScenario,
)
from etl_target_fabric.capacity import (
    CapacitySettings as CapacitySettings,
)
from etl_target_fabric.capacity import (
    CapacityStaticProfile as CapacityStaticProfile,
)
from etl_target_fabric.capacity import (
    CapacityUpdate as CapacityUpdate,
)
from etl_target_fabric.capacity import (
    CapacityWorkflowEstimate as CapacityWorkflowEstimate,
)
from etl_target_fabric.capacity import (
    CapacityWorkflowInput as CapacityWorkflowInput,
)
from etl_target_fabric.capacity import (
    build_capacity_profile as build_capacity_profile,
)
from etl_target_fabric.capacity import (
    build_informatica_capacity_profile as build_informatica_capacity_profile,
)
from etl_target_fabric.capacity import (
    capacity_csv as capacity_csv,
)
from etl_target_fabric.capacity import (
    estimate_capacity as estimate_capacity,
)
