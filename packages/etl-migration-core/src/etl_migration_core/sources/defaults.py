"""Default source adapter registry."""

from collections.abc import Collection

from etl_migration_core.plugins import PluginErrorMode, effective_plugin_allowlist
from etl_migration_core.sources.alteryx import AlteryxSourceAdapter
from etl_migration_core.sources.informatica_idmc import IdmcSourceAdapter
from etl_migration_core.sources.informatica_powercenter import PowerCenterSourceAdapter
from etl_migration_core.sources.registry import SourceAdapterRegistry


def create_default_registry(
    *,
    load_entry_points: bool = True,
    plugin_errors: PluginErrorMode = "record",
    plugin_allowlist: Collection[str] | None = None,
) -> SourceAdapterRegistry:
    """Create the built-in adapter registry in deterministic identity order.

    A broken installed plugin is recorded in ``plugin_results`` instead of preventing
    the built-in adapters from loading; pass ``plugin_errors="raise"`` for strict CI checks.
    ``plugin_allowlist=None`` applies the ``ACCELERATOR_PLUGIN_ALLOWLIST`` policy (every
    installed plugin when it is unset); pass a collection to override it.
    """
    registry = SourceAdapterRegistry(
        (
            AlteryxSourceAdapter(),
            IdmcSourceAdapter(),
            PowerCenterSourceAdapter(),
        )
    )
    if load_entry_points:
        registry.load_entry_points(
            allowlist=effective_plugin_allowlist(plugin_allowlist), on_error=plugin_errors
        )
    return registry


def with_builtin_adapters(registry: SourceAdapterRegistry | None) -> SourceAdapterRegistry:
    """Return a registry that holds every built-in adapter plus the adapters in ``registry``.

    Discovery uses this so that built-in formats are recognized identically whether or not
    a caller injected a registry that only contains plugins.
    """
    builtins = create_default_registry(load_entry_points=False)
    if registry is None:
        return builtins
    supplied = {adapter.adapter_id for adapter in registry.adapters}
    missing = [adapter for adapter in builtins.adapters if adapter.adapter_id not in supplied]
    if not missing:
        return registry
    return SourceAdapterRegistry((*registry.adapters, *missing))
