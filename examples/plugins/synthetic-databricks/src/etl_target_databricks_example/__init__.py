"""Synthetic, manual-review-only target-provider example."""

from etl_migration_core.contracts.ir import (
    EXTENSIBLE_SOURCE_IR_VERSION,
    IR_VERSION,
    EtlAsset,
    EtlPackage,
)
from etl_migration_core.contracts.spi import (
    TargetCapability,
    TargetEvaluation,
    TargetPlatformInfo,
)


class SyntheticDatabricksEvaluator:
    """Return a conservative result without claiming Databricks compatibility."""

    def evaluate_asset(
        self, package: EtlPackage, asset: EtlAsset, *, base_reason: str
    ) -> TargetEvaluation:
        return TargetEvaluation(
            platform_id="databricks",
            recommended_target="Manual review",
            recommendation_reason=base_reason,
            diagnostics=(
                "Synthetic example only; Databricks semantics and bindings are not assessed.",
            ),
        )


class SyntheticDatabricksProvider:
    """Demonstrate an independently installed evaluate-only provider."""

    platform_id = "databricks"
    display_name = "Synthetic Databricks example"
    provider_version = "0.1.0"
    supported_ir_versions = (IR_VERSION, EXTENSIBLE_SOURCE_IR_VERSION)
    implemented = True
    capabilities: tuple[TargetCapability, ...] = ("evaluate",)
    description = "Synthetic example only; all assets require manual review."

    def info(self) -> TargetPlatformInfo:
        return TargetPlatformInfo(
            platform_id=self.platform_id,
            display_name=self.display_name,
            provider_version=self.provider_version,
            supported_ir_versions=self.supported_ir_versions,
            implemented=self.implemented,
            status="ready",
            capabilities=self.capabilities,
            description=self.description,
        )

    def evaluator(self) -> SyntheticDatabricksEvaluator:
        return SyntheticDatabricksEvaluator()
