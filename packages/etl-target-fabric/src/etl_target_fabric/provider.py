"""Microsoft Fabric target-platform provider implementing the Target SPI."""

from __future__ import annotations

from collections.abc import Sequence
from pathlib import Path

from etl_migration_core.ir import IR_VERSION, EtlAsset, EtlPackage
from etl_migration_core.spi import (
    TargetCapability,
    TargetEvaluation,
    TargetEvaluator,
    TargetPlatformInfo,
)
from etl_target_fabric.evaluator import (
    evaluate_alteryx_native_route,
    evaluate_etl_native_route,
)


class FabricTargetEvaluator:
    """Compiler-grounded Microsoft Fabric fit evaluator."""

    def evaluate_alteryx_path(
        self,
        path: Path,
        *,
        unsupported_tools: Sequence[str],
        default_target: str,
        default_components: Sequence[str],
        default_reason: str,
    ) -> TargetEvaluation:
        return evaluate_alteryx_native_route(
            path,
            unsupported_tools=unsupported_tools,
            default_target=default_target,
            default_components=default_components,
            default_reason=default_reason,
        )

    def evaluate_asset(
        self,
        package: EtlPackage,
        asset: EtlAsset,
        *,
        base_reason: str,
    ) -> TargetEvaluation:
        return evaluate_etl_native_route(
            package,
            asset,
            base_reason=base_reason,
        )


class FabricTargetProvider:
    """Microsoft Fabric target platform provider plugin."""

    platform_id = "fabric"
    display_name = "Microsoft Fabric"
    provider_version = "1.0.0"
    supported_ir_versions: tuple[str, ...] = (IR_VERSION,)
    implemented = True
    capabilities: tuple[TargetCapability, ...] = (
        "evaluate",
        "capacity",
        "codegen",
        "dry_run",
    )
    description = (
        "Compiler-grounded evaluation, F-SKU capacity sizing, Dataflow Gen2 / "
        "PySpark Notebook / Data Pipeline generation, and dry-run planning."
    )

    def __init__(self) -> None:
        self._evaluator = FabricTargetEvaluator()

    def info(self) -> TargetPlatformInfo:
        return TargetPlatformInfo(
            platform_id=self.platform_id,
            display_name=self.display_name,
            provider_version=self.provider_version,
            supported_ir_versions=self.supported_ir_versions,
            implemented=True,
            status="ready",
            capabilities=self.capabilities,
            description=self.description,
        )

    def evaluator(self) -> TargetEvaluator:
        return self._evaluator
