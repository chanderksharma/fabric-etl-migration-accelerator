"""Compatibility re-export of source adapter registry."""

from etl_migration_core.sources.registry import (
    SOURCE_ENTRY_POINT_GROUP as SOURCE_ENTRY_POINT_GROUP,
)
from etl_migration_core.sources.registry import (
    AmbiguousSourceFormatError as AmbiguousSourceFormatError,
)
from etl_migration_core.sources.registry import (
    DetectedSource as DetectedSource,
)
from etl_migration_core.sources.registry import (
    SourceAdapterRegistry as SourceAdapterRegistry,
)
from etl_migration_core.sources.registry import (
    UnknownSourceFormatError as UnknownSourceFormatError,
)
