"""Fail-closed roadmap placeholder providers for future target platforms."""

from __future__ import annotations

from dataclasses import dataclass

from etl_migration_core.contracts.spi import (
    TargetCapability,
    TargetEvaluator,
    TargetPlatformInfo,
    UnsupportedTargetCapabilityError,
)


@dataclass(frozen=True, slots=True)
class PlaceholderTargetProvider:
    """Metadata-only fail-closed target placeholder superseded by external plugins."""

    platform_id: str
    display_name: str
    description: str
    provider_version: str = "0.0.0-placeholder"
    supported_ir_versions: tuple[str, ...] = ("1.0.0",)
    implemented: bool = False
    capabilities: tuple[TargetCapability, ...] = ()

    def info(self) -> TargetPlatformInfo:
        return TargetPlatformInfo(
            platform_id=self.platform_id,
            display_name=self.display_name,
            provider_version=self.provider_version,
            supported_ir_versions=self.supported_ir_versions,
            implemented=False,
            status="placeholder",
            capabilities=(),
            description=self.description,
        )

    def evaluator(self) -> TargetEvaluator | None:
        return None

    def require_capability(self, capability: str) -> None:
        raise UnsupportedTargetCapabilityError(
            self.platform_id,
            f"Target platform '{self.platform_id}' ({self.display_name}) "
            f"cannot run '{capability}' because it is a roadmap placeholder.",
        )


def builtin_placeholder_providers() -> tuple[PlaceholderTargetProvider, ...]:
    """Return built-in fail-closed placeholder registrations for roadmap targets."""
    return (
        PlaceholderTargetProvider(
            platform_id="databricks",
            display_name="Azure Databricks",
            description=(
                "Roadmap placeholder for Databricks target-fit evaluation, "
                "DBU sizing, Lakeflow/PySpark generation, and Asset Bundles."
            ),
        ),
        PlaceholderTargetProvider(
            platform_id="synapse",
            display_name="Azure Synapse Analytics",
            description=(
                "Roadmap placeholder for optional Synapse DWU and Spark pipeline "
                "targets (Synapse is primarily treated as a migration source estate)."
            ),
        ),
        PlaceholderTargetProvider(
            platform_id="snowflake",
            display_name="Snowflake",
            description=(
                "Roadmap placeholder for Snowflake target-fit evaluation, "
                "warehouse credit sizing, Snowpark, and SQL compilation."
            ),
        ),
    )
