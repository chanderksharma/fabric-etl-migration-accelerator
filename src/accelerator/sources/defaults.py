"""Default source adapter registry."""

from accelerator.sources.alteryx import AlteryxSourceAdapter
from accelerator.sources.informatica_idmc import IdmcSourceAdapter
from accelerator.sources.informatica_powercenter import PowerCenterSourceAdapter
from accelerator.sources.registry import SourceAdapterRegistry


def create_default_registry() -> SourceAdapterRegistry:
    """Create the built-in adapter registry in deterministic identity order."""
    return SourceAdapterRegistry(
        (
            AlteryxSourceAdapter(),
            IdmcSourceAdapter(),
            PowerCenterSourceAdapter(),
        )
    )
