"""Microsoft Fabric target-platform provider implementing the Target SPI."""

from __future__ import annotations

from collections.abc import Sequence
from pathlib import Path

from etl_migration_core.contracts.ir import EtlAsset, EtlPackage, SourcePlatform
from etl_migration_core.contracts.spi import (
    TargetArtifact,
    TargetCapability,
    TargetCapacityRecommendation,
    TargetCapacityResult,
    TargetEvaluation,
    TargetGenerationResult,
    TargetPlatformInfo,
)
from etl_target_fabric.assessment.ir_assessment import assess_package
from etl_target_fabric.capacity.model import (
    CAPACITY_MODEL_VERSION,
    CapacitySettings,
    CapacityWorkflowInput,
    build_informatica_capacity_profile,
    estimate_capacity,
)
from etl_target_fabric.compilers.ir import (
    SUPPORTED_IR_VERSIONS,
    CompilationTarget,
    compile_asset,
)
from etl_target_fabric.evaluation.native_route import (
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


class FabricTargetCodeGenerator:
    """TargetCodeGenerator implementation for Microsoft Fabric."""

    supported_target_kinds: tuple[str, ...] = ("dataflow", "notebook", "pipeline")

    def generate_package(
        self,
        package: EtlPackage,
        *,
        target_kind: str,
        display_path: str | None = None,
    ) -> TargetGenerationResult:
        if target_kind not in self.supported_target_kinds:
            raise ValueError(f"Unsupported Fabric target kind: {target_kind}")
        target: CompilationTarget = (
            "dataflow"
            if target_kind == "dataflow"
            else "notebook"
            if target_kind == "notebook"
            else "pipeline"
        )
        prefix = display_path or package.export_id
        artifacts: list[TargetArtifact] = []
        for asset in package.assets:
            compiled = compile_asset(package, asset, target)
            asset_path = "/".join(part for part in (asset.folder, asset.name) if part)
            workflow = f"{prefix}!{asset_path}" if asset_path else prefix
            artifacts.append(
                TargetArtifact(
                    workflow=workflow,
                    target_kind=target,
                    validation_state=compiled.validation_state,
                    translation_mode=(
                        "native"
                        if compiled.validation_state == "generated_unvalidated"
                        else "scaffold"
                    ),
                    deployable=compiled.deployable,
                    files={
                        f"{target}-source": compiled.code,
                    },
                    diagnostics=compiled.diagnostics,
                    required_bindings=compiled.required_bindings,
                    metadata={
                        "asset_id": asset.native_id,
                        "runtime_ready": compiled.runtime_ready,
                        "definition_queries": list(compiled.definition_queries),
                        "loaded_outputs": list(compiled.loaded_outputs),
                    },
                )
            )
        return TargetGenerationResult(
            platform_id="fabric",
            provider_version="1.0.0",
            target_kind=target,
            artifacts=tuple(artifacts),
        )


class FabricTargetCapacityEstimator:
    """TargetCapacityEstimator implementation for Microsoft Fabric F-SKU sizing."""

    def estimate_package_capacity(self, package: EtlPackage) -> TargetCapacityResult:
        if not isinstance(package.source_platform, SourcePlatform):
            raise ValueError(
                f"Fabric capacity estimation does not support source {package.source_platform!r}"
            )
        from etl_target_fabric.assessment.portfolio import assessment_response

        assessments = [
            assessment_response(
                package.export_id,
                evaluate_item,
                capacity_profile=build_informatica_capacity_profile(package, asset),
            )
            for asset, evaluate_item in zip(
                package.assets, assess_package(package), strict=True
            )
        ]
        inputs = {
            item.path: CapacityWorkflowInput(workflow_path=item.path)
            for item in assessments
            if item.capacity_profile is not None
        }
        estimate = estimate_capacity(assessments, inputs, CapacitySettings())
        return TargetCapacityResult(
            platform_id="fabric",
            provider_version="1.0.0",
            model_version=CAPACITY_MODEL_VERSION,
            status=estimate.status,
            asset_count=estimate.workflow_count,
            modeled_count=estimate.modeled_count,
            excluded_count=estimate.excluded_count,
            summary_metrics={
                "monthly_cu_hours": estimate.monthly_cu_hours,
                "daily_cu_seconds": estimate.daily_cu_seconds,
                "coverage_percent": estimate.coverage_percent,
            },
            recommendations=tuple(
                TargetCapacityRecommendation(
                    scenario=scenario.name,
                    required_units=scenario.required_cu,
                    unit_label="CU",
                    recommended_tier=scenario.recommended_sku,
                )
                for scenario in estimate.scenarios
            ),
        )


class FabricTargetProvider:
    """Microsoft Fabric target platform provider plugin."""

    platform_id = "fabric"
    display_name = "Microsoft Fabric"
    provider_version = "1.0.0"
    supported_ir_versions: tuple[str, ...] = SUPPORTED_IR_VERSIONS
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
        self._code_generator = FabricTargetCodeGenerator()
        self._capacity_estimator = FabricTargetCapacityEstimator()

    def info(self) -> TargetPlatformInfo:
        return TargetPlatformInfo(
            platform_id=self.platform_id,
            display_name=self.display_name,
            provider_version=self.provider_version,
            supported_ir_versions=self.supported_ir_versions,
            implemented=True,
            status="ready",
            capabilities=self.capabilities,
            target_kinds=self._code_generator.supported_target_kinds,
            description=self.description,
        )

    def evaluator(self) -> FabricTargetEvaluator:
        return self._evaluator

    def code_generator(self) -> FabricTargetCodeGenerator:
        return self._code_generator

    def capacity_estimator(self) -> FabricTargetCapacityEstimator:
        return self._capacity_estimator
