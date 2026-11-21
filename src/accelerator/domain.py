"""Compatibility contract entrypoint for SUPPORTED_EXTENSIONS."""

from etl_migration_core.intake.domain import (
    SUPPORTED_EXTENSIONS as SUPPORTED_EXTENSIONS,
)
from etl_migration_core.intake.domain import (
    DiscoveryLimits as DiscoveryLimits,
)
from etl_migration_core.intake.domain import (
    DiscoverySummary as DiscoverySummary,
)
from etl_migration_core.intake.domain import (
    InputKind as InputKind,
)
from etl_migration_core.intake.domain import (
    SkippedItem as SkippedItem,
)
from etl_migration_core.intake.domain import (
    SkipReason as SkipReason,
)
from etl_migration_core.intake.domain import (
    WorkflowCandidate as WorkflowCandidate,
)
from etl_migration_core.intake.domain import (
    classify_input as classify_input,
)
