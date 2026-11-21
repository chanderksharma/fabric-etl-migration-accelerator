"""Default source adapter registry."""

from etl_migration_core.sources.alteryx import AlteryxSourceAdapter
from etl_migration_core.sources.informatica_idmc import IdmcSourceAdapter
from etl_migration_core.sources.informatica_powercenter import PowerCenterSourceAdapter
from etl_migration_core.sources.registry import SourceAdapterRegistry


def create_default_registry(*, load_entry_points: bool = True) -> SourceAdapterRegistry:
    """Create the built-in adapter registry in deterministic identity order."""
    registry = SourceAdapterRegistry(
        (
            AlteryxSourceAdapter(),
            IdmcSourceAdapter(),
            PowerCenterSourceAdapter(),
        )
    )
    if load_entry_points:
        registry.load_entry_points()
    return registry
