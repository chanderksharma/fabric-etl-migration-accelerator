"""Deterministic target-platform provider registration and discovery."""

from __future__ import annotations

from collections.abc import Collection, Iterable, Iterator, Sequence
from contextlib import contextmanager
from importlib.metadata import entry_points
from pathlib import Path

from pydantic import BaseModel, ConfigDict

from etl_migration_core.contracts.ir import EtlAsset, EtlPackage, is_ir_compatible
from etl_migration_core.contracts.spi import (
    AlteryxPathTargetEvaluator,
    TargetArtifact,
    TargetCapacityProvider,
    TargetCapacityResult,
    TargetCodeGeneratorProvider,
    TargetDeploymentProvider,
    TargetDeploymentSpec,
    TargetDryRunProvider,
    TargetDryRunResult,
    TargetEvaluation,
    TargetGenerationResult,
    TargetPlatformInfo,
    TargetPlatformProvider,
    TargetValidationResult,
    TargetValidatorProvider,
    UnsupportedTargetCapabilityError,
)
from etl_migration_core.plugins import (
    EntryPointProvenance,
    PluginErrorMode,
    PluginLoadResult,
    fault_detail,
    require_compatible_spi,
)

TARGET_ENTRY_POINT_GROUP = "etl_migration.targets"
BUILTIN_ORIGIN = "builtin"


class UnknownTargetPlatformError(KeyError):
    """Raised when a requested target platform ID is not registered."""


class TargetProviderFaultError(ValueError):
    """A target provider raised an unexpected exception instead of a documented error."""


class TargetProviderFault(BaseModel):
    """One registered provider whose metadata could not be validated."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    platform_id: str
    detail: str


class TargetCatalog(BaseModel):
    """Validated provider metadata plus the providers that were excluded and why."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    targets: tuple[TargetPlatformInfo, ...]
    faults: tuple[TargetProviderFault, ...] = ()


@contextmanager
def _guard(provider: TargetPlatformProvider, action: str) -> Iterator[None]:
    """Contain unexpected provider exceptions; ValueError and capability errors pass through."""
    try:
        yield
    except (ValueError, OSError, UnsupportedTargetCapabilityError):
        raise
    except Exception as error:
        raise TargetProviderFaultError(
            f"Target provider '{provider.platform_id}' faulted during {action}: "
            f"{fault_detail(error)}"
        ) from error


def _advertised_target_kinds(provider: TargetPlatformProvider) -> tuple[str, ...]:
    """Return the target kinds the provider's code generator actually accepts."""
    if not isinstance(provider, TargetCodeGeneratorProvider):
        return ()
    generator = provider.code_generator()
    return tuple(generator.supported_target_kinds) if generator is not None else ()


def _validated_info(provider: TargetPlatformProvider) -> TargetPlatformInfo:
    with _guard(provider, "describe"):
        info = provider.info()
        target_kinds = _advertised_target_kinds(provider)
    if (
        info.platform_id.strip().casefold() != provider.platform_id.strip().casefold()
        or info.provider_version != provider.provider_version
        or info.supported_ir_versions != provider.supported_ir_versions
        or info.implemented != provider.implemented
        or info.capabilities != provider.capabilities
        or info.target_kinds != target_kinds
        or info.status != ("ready" if provider.implemented else "placeholder")
    ):
        raise ValueError(f"Target provider '{provider.platform_id}' returned inconsistent metadata")
    return info


class TargetPlatformRegistry:
    """Register and resolve pluggable target-platform providers."""

    def __init__(self, providers: Iterable[TargetPlatformProvider] = ()) -> None:
        self._providers: dict[str, TargetPlatformProvider] = {}
        self._origins: dict[str, str] = {}
        self._plugin_results: list[PluginLoadResult] = []
        for provider in providers:
            self.register(provider)

    @property
    def providers(self) -> tuple[TargetPlatformProvider, ...]:
        """Return registered providers in deterministic platform_id order."""
        return tuple(self._providers[key] for key in sorted(self._providers))

    @property
    def plugin_results(self) -> tuple[PluginLoadResult, ...]:
        """Return the outcome of every entry point considered by ``load_entry_points``."""
        return tuple(self._plugin_results)

    def origin_of(self, platform_id: str) -> str:
        """Return ``builtin`` or ``plugin:<entry point>`` for a registered provider."""
        return self._origins[platform_id.strip().casefold()]

    def register(
        self,
        provider: TargetPlatformProvider,
        *,
        replace_placeholder: bool = False,
        origin: str = BUILTIN_ORIGIN,
    ) -> None:
        """Register one unique target platform provider."""
        require_compatible_spi(provider, f"target provider {type(provider).__name__}")
        platform_id = provider.platform_id.strip().casefold()
        if not platform_id:
            raise ValueError("target platform_id is required")
        existing = self._providers.get(platform_id)
        if existing is not None:
            if replace_placeholder and not existing.implemented:
                self._providers[platform_id] = provider
                self._origins[platform_id] = origin
                return
            raise ValueError(f"duplicate target platform provider: {platform_id}")
        self._providers[platform_id] = provider
        self._origins[platform_id] = origin

    def load_entry_points(
        self,
        group: str = TARGET_ENTRY_POINT_GROUP,
        *,
        allowlist: Collection[str] | None = None,
        on_error: PluginErrorMode = "raise",
    ) -> int:
        """Discover installed target provider plugins via importlib.metadata.

        ``on_error="record"`` isolates a broken plugin: it is reported in
        ``plugin_results`` and every other provider still loads. ``allowlist`` limits
        loading to the named entry points.
        """
        loaded = 0
        discovered: set[str] = set()
        for ep in sorted(entry_points(group=group), key=lambda item: item.name):
            provenance = EntryPointProvenance.of(ep, group)
            if allowlist is not None and ep.name not in allowlist:
                self._plugin_results.append(provenance.skipped("not in the plugin allowlist"))
                continue
            try:
                factory = ep.load()
                provider = factory() if callable(factory) else factory
                key = provider.platform_id.strip().casefold()
                if key in discovered:
                    raise ValueError(f"duplicate target platform entry point: {key}")
                existing = self._providers.get(key)
                if existing is not None and existing.implemented:
                    if type(existing) is type(provider) and existing.info() == provider.info():
                        discovered.add(key)
                        self._plugin_results.append(provenance.loaded(key))
                        continue
                    raise ValueError(f"duplicate target platform provider: {key}")
                self.register(provider, replace_placeholder=True, origin=f"plugin:{ep.name}")
                discovered.add(key)
            except Exception as error:
                if on_error == "raise":
                    raise
                self._plugin_results.append(provenance.failed(error))
                continue
            self._plugin_results.append(provenance.loaded(key))
            loaded += 1
        return loaded

    def get(self, platform_id: str) -> TargetPlatformProvider:
        """Return a registered provider regardless of implementation status."""
        key = platform_id.strip().casefold()
        provider = self._providers.get(key)
        if provider is None:
            raise UnknownTargetPlatformError(f"Unknown target platform: {platform_id}")
        return provider

    def require_implemented(
        self,
        platform_id: str,
        *,
        capability: str | None = None,
    ) -> TargetPlatformProvider:
        """Return an implemented provider or fail closed for placeholders."""
        provider = self.get(platform_id)
        _validated_info(provider)
        if not provider.implemented:
            raise UnsupportedTargetCapabilityError(
                provider.platform_id,
                f"Target platform '{provider.platform_id}' ({provider.display_name}) "
                "is registered as a roadmap placeholder and is not yet implemented.",
            )
        if capability is not None and capability not in provider.capabilities:
            raise UnsupportedTargetCapabilityError(
                provider.platform_id,
                f"Target platform '{provider.platform_id}' does not support "
                f"capability '{capability}'.",
            )
        return provider

    def get_info(self, platform_id: str) -> TargetPlatformInfo:
        """Return validated capability metadata for one target platform."""
        return _validated_info(self.get(platform_id))

    def evaluate_asset(
        self,
        platform_id: str,
        package: EtlPackage,
        asset: EtlAsset,
        *,
        base_reason: str,
    ) -> TargetEvaluation:
        """Evaluate a canonical asset after checking capability and IR compatibility."""
        provider = self.require_implemented(platform_id, capability="evaluate")
        if not is_ir_compatible(package.ir_version, provider.supported_ir_versions):
            raise ValueError(
                f"Target platform '{provider.platform_id}' does not support "
                f"IR version {package.ir_version!r}"
            )
        if asset not in package.assets:
            raise ValueError("Asset does not belong to the supplied ETL package")
        with _guard(provider, "evaluation"):
            evaluator = provider.evaluator()
            if evaluator is None:
                raise UnsupportedTargetCapabilityError(
                    provider.platform_id,
                    f"Target platform '{provider.platform_id}' advertises evaluation "
                    "but does not provide an evaluator.",
                )
            evaluation = evaluator.evaluate_asset(package, asset, base_reason=base_reason)
        if evaluation.platform_id.strip().casefold() != provider.platform_id.strip().casefold():
            raise ValueError("Target evaluator returned a different platform identity")
        return evaluation

    def evaluate_alteryx_path(
        self,
        platform_id: str,
        path: Path,
        *,
        unsupported_tools: Sequence[str],
        default_target: str,
        default_components: Sequence[str],
        default_reason: str,
    ) -> TargetEvaluation:
        """Evaluate a staged Alteryx workflow through a provider's optional path evaluator.

        Alteryx generation still reads the legacy workflow graph rather than canonical IR,
        so a provider that confirms Alteryx routes does so from the staged file. Providers
        without the optional protocol fail closed here and can use ``evaluate_asset``.
        """
        provider = self.require_implemented(platform_id, capability="evaluate")
        with _guard(provider, "evaluation"):
            evaluator = provider.evaluator()
            if not isinstance(evaluator, AlteryxPathTargetEvaluator):
                raise UnsupportedTargetCapabilityError(
                    provider.platform_id,
                    f"Target platform '{provider.platform_id}' does not evaluate "
                    "staged Alteryx workflow paths.",
                )
            evaluation = evaluator.evaluate_alteryx_path(
                path,
                unsupported_tools=unsupported_tools,
                default_target=default_target,
                default_components=default_components,
                default_reason=default_reason,
            )
        if evaluation.platform_id.strip().casefold() != provider.platform_id.strip().casefold():
            raise ValueError("Target evaluator returned a different platform identity")
        return evaluation

    def generate_package(
        self,
        platform_id: str,
        package: EtlPackage,
        *,
        target_kind: str,
        display_path: str | None = None,
    ) -> TargetGenerationResult:
        """Generate target artifacts for a canonical package via TargetCodeGeneratorProvider."""
        provider = self.require_implemented(platform_id, capability="codegen")
        if not is_ir_compatible(package.ir_version, provider.supported_ir_versions):
            raise ValueError(
                f"Target platform '{provider.platform_id}' does not support "
                f"IR version {package.ir_version!r}"
            )
        with _guard(provider, "generation"):
            generator = (
                provider.code_generator()
                if isinstance(provider, TargetCodeGeneratorProvider)
                else None
            )
            if generator is None:
                raise UnsupportedTargetCapabilityError(
                    provider.platform_id,
                    f"Target platform '{provider.platform_id}' advertises codegen "
                    "but does not provide a code generator.",
                )
            if target_kind not in generator.supported_target_kinds:
                raise UnsupportedTargetCapabilityError(
                    provider.platform_id,
                    f"Target platform '{provider.platform_id}' does not support "
                    f"target kind {target_kind!r}.",
                )
            result = generator.generate_package(
                package,
                target_kind=target_kind,
                display_path=display_path,
            )
        if result.platform_id.strip().casefold() != provider.platform_id.strip().casefold():
            raise ValueError("Target code generator returned a different platform identity")
        return result

    def estimate_capacity(
        self,
        platform_id: str,
        package: EtlPackage,
    ) -> TargetCapacityResult:
        """Estimate target capacity for a canonical package via TargetCapacityProvider."""
        provider = self.require_implemented(platform_id, capability="capacity")
        if not is_ir_compatible(package.ir_version, provider.supported_ir_versions):
            raise ValueError(
                f"Target platform '{provider.platform_id}' does not support "
                f"IR version {package.ir_version!r}"
            )
        with _guard(provider, "capacity estimation"):
            estimator = (
                provider.capacity_estimator()
                if isinstance(provider, TargetCapacityProvider)
                else None
            )
            if estimator is None:
                raise UnsupportedTargetCapabilityError(
                    provider.platform_id,
                    f"Target platform '{provider.platform_id}' advertises capacity "
                    "but does not provide a capacity estimator.",
                )
            result = estimator.estimate_package_capacity(package)
        if result.platform_id.strip().casefold() != provider.platform_id.strip().casefold():
            raise ValueError("Target capacity estimator returned a different platform identity")
        return result

    def validate_artifacts(
        self,
        platform_id: str,
        artifacts: Sequence[TargetArtifact],
    ) -> TargetValidationResult:
        """Validate generated target artifacts via TargetValidatorProvider."""
        provider = self.require_implemented(platform_id, capability="validate")
        with _guard(provider, "validation"):
            validator = (
                provider.validator()
                if isinstance(provider, TargetValidatorProvider)
                else None
            )
            if validator is None:
                raise UnsupportedTargetCapabilityError(
                    provider.platform_id,
                    f"Target platform '{provider.platform_id}' advertises validate "
                    "but does not provide a validator.",
                )
            result = validator.validate_artifacts(artifacts)
        if result.platform_id.strip().casefold() != provider.platform_id.strip().casefold():
            raise ValueError("Target validator returned a different platform identity")
        return result

    def plan_dry_run(
        self,
        platform_id: str,
        artifacts: Sequence[TargetArtifact],
        *,
        approved_destination: str | None,
        requested_destination: str,
    ) -> TargetDryRunResult:
        """Plan a network-free deployment dry run via TargetDryRunProvider."""
        provider = self.require_implemented(platform_id, capability="dry_run")
        with _guard(provider, "dry-run planning"):
            planner = (
                provider.dry_run_planner()
                if isinstance(provider, TargetDryRunProvider)
                else None
            )
            if planner is None:
                raise UnsupportedTargetCapabilityError(
                    provider.platform_id,
                    f"Target platform '{provider.platform_id}' advertises dry_run "
                    "but does not provide a dry-run planner.",
                )
            result = planner.plan_dry_run(
                artifacts,
                approved_destination=approved_destination,
                requested_destination=requested_destination,
            )
        if result.platform_id.strip().casefold() != provider.platform_id.strip().casefold():
            raise ValueError("Target dry-run planner returned a different platform identity")
        return result

    def build_deployment_spec(
        self,
        platform_id: str,
        *,
        target_kind: str,
        destination: str,
        artifact_path: str,
        conflict_behavior: str = "Fail",
    ) -> TargetDeploymentSpec:
        """Build CI/CD deployment dispatch inputs via TargetDeploymentProvider."""
        provider = self.require_implemented(platform_id, capability="deploy")
        with _guard(provider, "deployment planning"):
            adapter = (
                provider.deployment_adapter()
                if isinstance(provider, TargetDeploymentProvider)
                else None
            )
            if adapter is None:
                raise UnsupportedTargetCapabilityError(
                    provider.platform_id,
                    f"Target platform '{provider.platform_id}' advertises deploy "
                    "but does not provide a deployment adapter.",
                )
            spec = adapter.build_deployment_spec(
                target_kind=target_kind,
                destination=destination,
                artifact_path=artifact_path,
                conflict_behavior=conflict_behavior,
            )
        if spec.platform_id.strip().casefold() != provider.platform_id.strip().casefold():
            raise ValueError("Target deployment adapter returned a different platform identity")
        return spec

    def list_providers(self) -> tuple[TargetPlatformInfo, ...]:
        """Return serializable capability metadata for every registered target."""
        return tuple(_validated_info(provider) for provider in self.providers)

    def catalog(self) -> TargetCatalog:
        """Return valid provider metadata and isolate providers that fail validation."""
        targets: list[TargetPlatformInfo] = []
        faults: list[TargetProviderFault] = []
        for key in sorted(self._providers):
            try:
                targets.append(_validated_info(self._providers[key]))
            except (ValueError, OSError) as error:
                faults.append(TargetProviderFault(platform_id=key, detail=fault_detail(error)))
        return TargetCatalog(targets=tuple(targets), faults=tuple(faults))
