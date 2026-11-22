"""Plugin load bookkeeping shared by the source and target registries."""

from __future__ import annotations

import logging
import os
from collections.abc import Collection, Mapping
from dataclasses import dataclass
from typing import Literal

from pydantic import BaseModel, ConfigDict

from etl_migration_core.contracts.ir import is_ir_compatible
from etl_migration_core.contracts.spi import IR_SPI_VERSION

logger = logging.getLogger(__name__)

PLUGIN_ALLOWLIST_ENV = "ACCELERATOR_PLUGIN_ALLOWLIST"
PluginErrorMode = Literal["raise", "record"]
_MAX_DETAIL_CHARS = 300


class PluginLoadResult(BaseModel):
    """Outcome of loading one installed entry point."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    group: str
    name: str
    status: Literal["loaded", "failed", "skipped"]
    provides: str | None = None
    detail: str | None = None
    distribution: str | None = None
    distribution_version: str | None = None


def plugin_allowlist_from_environment(
    environ: Mapping[str, str] | None = None,
) -> frozenset[str] | None:
    """Return the approved entry-point names, or None when every installed plugin may load."""
    raw = (os.environ if environ is None else environ).get(PLUGIN_ALLOWLIST_ENV, "")
    names = frozenset(token.strip() for token in raw.split(",") if token.strip())
    return names or None


def effective_plugin_allowlist(explicit: Collection[str] | None = None) -> Collection[str] | None:
    """Resolve which entry points may load: an explicit allowlist wins, else the process policy.

    The default registry factories use this so the operator's allowlist holds on every path
    that builds a registry, including library facades and stateless CLIs.
    """
    return explicit if explicit is not None else plugin_allowlist_from_environment()


def require_compatible_spi(component: object, label: str) -> None:
    """Reject a plugin whose SPI version is not the host's.

    A missing ``spi_version`` means ``1.0.0``, so built-ins and placeholders keep
    loading. An incompatible declaration, including ``2.0.0``, fails registration.
    """
    declared = getattr(component, "spi_version", None)
    version = IR_SPI_VERSION if declared is None else declared
    if not isinstance(version, str) or not is_ir_compatible(version, (IR_SPI_VERSION,)):
        raise ValueError(
            f"{label} SPI version {version!r} is incompatible with {IR_SPI_VERSION}"
        )


def fault_detail(error: BaseException) -> str:
    """Summarize an exception without a traceback so it is safe to show to users."""
    message = " ".join(str(error).split())
    text = f"{type(error).__name__}: {message}" if message else type(error).__name__
    return text if len(text) <= _MAX_DETAIL_CHARS else text[: _MAX_DETAIL_CHARS - 1] + "…"


@dataclass(frozen=True, slots=True)
class EntryPointProvenance:
    """Distribution identity of one entry point, used to build load results."""

    group: str
    name: str
    distribution: str | None = None
    distribution_version: str | None = None

    @classmethod
    def of(cls, entry_point: object, group: str) -> EntryPointProvenance:
        """Read the owning distribution when the entry point exposes it."""
        distribution = getattr(entry_point, "dist", None)
        return cls(
            group=group,
            name=str(getattr(entry_point, "name", "")),
            distribution=getattr(distribution, "name", None),
            distribution_version=getattr(distribution, "version", None),
        )

    def loaded(self, provides: str) -> PluginLoadResult:
        return self._result("loaded", provides=provides)

    def skipped(self, reason: str) -> PluginLoadResult:
        return self._result("skipped", detail=reason)

    def failed(self, error: BaseException) -> PluginLoadResult:
        logger.warning(
            "Plugin %s/%s failed to load: %s", self.group, self.name, fault_detail(error)
        )
        return self._result("failed", detail=fault_detail(error))

    def _result(
        self,
        status: Literal["loaded", "failed", "skipped"],
        *,
        provides: str | None = None,
        detail: str | None = None,
    ) -> PluginLoadResult:
        return PluginLoadResult(
            group=self.group,
            name=self.name,
            status=status,
            provides=provides,
            detail=detail,
            distribution=self.distribution,
            distribution_version=self.distribution_version,
        )
