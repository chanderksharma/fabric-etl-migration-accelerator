---
title: Building Source and Target Plugins
description: Developer guide for extending etl-migration-core with custom source adapters, target platform providers, and stateless IDE integrations
ms.date: 2026-11-22
ms.topic: how-to
---

## Architecture overview

The migration platform uses a modular microkernel workspace organized into three independent core packages and an application shell:

| Package | PyPI distribution | Responsibilities |
| :--- | :--- | :--- |
| Core IR and SPI | `etl-migration-core` | Canonical `EtlPackage` IR, secure discovery, built-in source parsers, `SourceAdapterRegistry`, `TargetPlatformRegistry`, and roadmap placeholders |
| Portfolio Assessment | `etl-portfolio-assessment` | Target-neutral asset inventory, complexity scoring, intrinsic effort, workload profiles, redacted evidence, and stateless `etl-assess` CLI |
| Microsoft Fabric Provider | `etl-target-fabric` | Fabric target-fit evaluator, F-SKU capacity model, Dataflow Gen2 / PySpark / Data Pipeline compilers, artifact writer, dry-run planner, and `etl-fabric` CLI |
| Application Shell | `fabric-etl-migration-accelerator` | FastAPI loopback server, SQLite WAL `RunService`, Typer CLI (`tool`), CI dispatchers, and Windows Desktop utility |

See [Figure ARCH-02](../Architecture/arch-02-pluggable-solution-architecture.vsdx.fig.png) and the [Pluggable Architecture Implementation Plan](../Planning/pluggable-architecture-implementation-plan.md) for full boundary contracts.

## Adding a target platform provider

Target platforms register via open string identifiers (`"fabric"`, `"databricks"`, `"synapse"`, `"snowflake"`, or custom IDs) using `importlib.metadata` entry points in group `etl_migration.targets`. Built-in roadmap placeholders (`databricks`, `synapse`, `snowflake`) fail closed until an implementing plugin wheel is installed.

The following example illustrates provider registration, not a complete or
validated Databricks evaluator. A real evaluator must check supported
semantics and report unsupported operations and required bindings. The
current provider protocol exposes metadata and evaluation; registering a
provider alone does not connect its generation or deployment to the local
application. See the [developer contribution guide](developer-contribution-guide.md)
for integration steps.

For an independently packaged, manual-review-only example, see the
[synthetic Databricks provider](../../examples/plugins/synthetic-databricks/README.md).
It is a contract demonstration, not Databricks product support.

### Implement the provider protocol

```python
from etl_migration_core.contracts.ir import IR_VERSION, EtlAsset, EtlPackage
from etl_migration_core.contracts.spi import (
    TargetCapability,
    TargetEvaluation,
    TargetEvaluator,
    TargetPlatformInfo,
)


class DatabricksEvaluator:
    def evaluate_asset(
        self,
        package: EtlPackage,
        asset: EtlAsset,
        *,
        base_reason: str,
    ) -> TargetEvaluation:
        return TargetEvaluation(
            platform_id="databricks",
            implemented=True,
            recommended_target="Databricks Lakeflow",
            target_components=("Lakeflow Pipeline",),
            recommendation_reason=base_reason,
        )


class DatabricksTargetProvider:
    platform_id = "databricks"
    display_name = "Azure Databricks"
    provider_version = "0.1.0"
    supported_ir_versions: tuple[str, ...] = (IR_VERSION,)
    implemented = True
    capabilities: tuple[TargetCapability, ...] = ("evaluate",)
    description = "Databricks target-fit evaluator."

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
        return DatabricksEvaluator()
```

### Register the entry point in `pyproject.toml`

```toml
[project.entry-points."etl_migration.targets"]
databricks = "etl_target_databricks.provider:DatabricksTargetProvider"
```

When installed alongside `etl-migration-core`, `create_target_registry()` automatically supersedes the built-in `"databricks"` placeholder with `DatabricksTargetProvider`, and `GET /api/targets` or `uv run tool targets` reports `"status": "ready"`.

Use `TargetPlatformRegistry.evaluate_asset` to check the advertised evaluation
capability and IR compatibility before calling the evaluator. Providers can also
implement the optional `@runtime_checkable` protocols `TargetCodeGeneratorProvider`
and `TargetCapacityProvider` from
`etl_migration_core.contracts.spi`, and declare SemVer minor compatibility ranges
such as `"1.*"` or `"^1.0.0"` via `supported_ir_versions`. A provider that implements
`TargetCodeGeneratorProvider` must also publish the kinds its generator accepts in
`TargetPlatformInfo.target_kinds` (for Fabric: `dataflow`, `notebook`, `pipeline`); the
registry rejects metadata that disagrees with the generator, and the portal offers only
the advertised kinds. There is no deployment SPI: CI dispatch is Fabric-specific today
and is not a pluggable capability. Use
`assert_source_adapter_conformance` and `assert_target_provider_conformance` in
`etl_migration_core.contracts.testing` to validate metadata consistency, determinism,
stream probing, and unsupported-IR rejection in plugin test suites. For completed local runs,
`POST /api/runs/{run_id}/targets/{platform_id}/evaluate` evaluates each confirmed
canonical asset and returns separate results without changing the existing assessment;
`POST /api/runs/{run_id}/targets/{platform_id}/generate?target_kind=...` and
`GET /api/runs/{run_id}/targets/{platform_id}/capacity` invoke registered `codegen`
and `capacity` providers.
Results are saved per run and platform, with the most recent evaluation replacing the
previous one. The endpoint does not enable target-specific generation or deployment
in the portal. The local runtime can project a Fabric `Candidate` into
`ArtifactSet` (`etl_migration_core.contracts.artifacts`). That projection
carries identity, validation state, and diagnostics, and leaves `files`
empty. It is not a package format, and it does not connect a plugin generator
to the portal. `write_candidates` remains the Fabric disk writer. Generation
jobs use the same compiler path and also do not write files. See
[System Architecture](../Architecture/system-architecture.md#local-generation-runtime). Provider metadata must match its declared version, IR versions,
implementation status, and capabilities. These fields are checked both when listing
providers and before invoking a capability. Duplicate provider entry points are rejected.

Registration calls `require_compatible_spi` in
`etl_migration_core.plugins` for both source adapters and target providers.
Omit `spi_version` to mean `1.0.0` (`IR_SPI_VERSION`). Set it only when you
intentionally declare the host contract. An incompatible value, including
`2.0.0`, fails registration and appears in `GET /api/plugins` as a load
failure. Built-in adapters keep loading because they omit the attribute.
The optional `AlteryxPathTargetEvaluator`
protocol preserves the legacy path-based Fabric method for existing integrations.
Completed runs save a neutral baseline alongside the existing Fabric-focused assessment.
Retrieve it with `GET /api/runs/{run_id}/neutral-assessment`. To generate or refresh
the baseline for an older completed run, use `POST` on the same path. The portal
shows external-source runs in a separate neutral workspace, with evaluation for
registered target providers that advertise the `evaluate` capability.

## Adding a source adapter plugin

Source adapters normalize native ETL exports (such as SSIS `.dtsx`, Talend, or DataStage) into `EtlPackage` and register under the `etl_migration.sources` entry-point group.

These formats are extension examples, not current built-in support. Canonical
packages accept new lowercase source identifiers; third-party sources use a
generic neutral workload profile. Identifiers start with a lowercase letter and
contain up to 64 lowercase letters, digits, dots, underscores, or hyphens.
External source packages must declare `EXTENSIBLE_SOURCE_IR_VERSION` (`1.1.0`)
or a later compatible version; existing built-in packages remain on IR `1.0.0`.
Target providers must explicitly advertise support for each IR version they accept.
Duplicate source adapter entry points are rejected. Existing Fabric evaluation and compilation
reject sources they have not certified. Adapters can declare
`supported_extensions` as lowercase extensions such as `(".dtsx",)` to enable
local-file and ZIP member discovery and target-neutral run assessment for extensions
not reserved by built-in intake. Each extension must be a dot followed by 1 to 16
lowercase letters, digits, hyphens, or underscores; registration rejects anything else,
including uppercase such as `".DTSX"`. New plugin file formats must use an external source identifier;
they cannot claim a built-in source identity through extension discovery.
External snapshots record the selected adapter identity and its adapter, parser,
registry, and rules versions. Changing any of these requires a new preview. Older
external snapshots without component versions also require a new preview. Plugin
authors must increment the appropriate version when its behavior changes; version
strings do not verify the installed code. Select **Installed plugins** in the
portal to assess external sources separately from built-in sources. The neutral
workspace does not generate or deploy target artifacts. An unsupported Fabric
assessment is reported separately from the neutral baseline and registered-target
evaluations. See the
[developer contribution guide](developer-contribution-guide.md#extend-a-source-system).

A [synthetic SSIS source adapter](../../examples/plugins/synthetic-ssis/README.md)
demonstrates local-file and archive discovery and manual-review-only metadata extraction.
It does not add production SSIS support.

```toml
[project.entry-points."etl_migration.sources"]
ssis = "etl_source_ssis.adapter:SsisSourceAdapter"
```

Keep source adapters strictly free of target-platform constructs (`Dataflow`, `Databricks`, `F-SKU`). Always parse untrusted XML using `defusedxml` with external entity expansion disabled, and never execute embedded workflow scripts.

### Failure isolation contract

The host treats every plugin as untrusted for availability (not for sandboxing; plugins
still run in-process with the application's privileges). Follow this contract so a bad
input never becomes a failed run:

- Return `None` from `probe` for content you do not recognize.
- Raise `ValueError` for content that is recognized but invalid, and `OSError` for
  unreadable files. These are reported as a skipped file or one failed workflow.
- Any other exception from `probe` or `parse` is isolated as an adapter fault
  (`SourceAdapterFaultError`, a `ValueError`) and reported with the adapter identity and
  stage. The same applies to target providers (`TargetProviderFaultError`).
- Read files with `etl_migration_core.sources.read_bounded(path, limit)`. It sizes the read
  from the real file size and rejects oversized or growing files, unlike `read(limit + 1)`,
  which allocates the full limit for every file.
- Importing the entry point must not have side effects. A plugin that fails to import,
  duplicates an existing identity, declares an identity or version attribute that is not a
  string, or declares an invalid `supported_extensions` entry is recorded in
  `registry.plugin_results` and `GET /api/plugins` while the built-in adapters keep
  working. `create_default_registry` and `create_default_target_registry` isolate
  failures by default; pass `plugin_errors="raise"` in a CI job that must fail on a broken
  plugin. Set `ACCELERATOR_PLUGIN_ALLOWLIST` to load only approved entry points: every
  default registry honors it, including the library facades and the stateless
  `etl-assess` and `etl-fabric` CLIs, and an explicit `plugin_allowlist=` argument
  overrides it.
- `GET /api/targets` returns the valid targets plus a `faults` list instead of failing the
  whole catalog when one provider reports inconsistent metadata.

Operations that cannot be isolated in-process, such as an infinite loop or a native
crash, are bounded by the run lease and quarantined after five interrupted attempts.

### Verify an installed plugin

Unit tests that import your adapter or provider directly do not prove packaging. After
installing your distribution next to the accelerator, run `uv run tool plugins`. It lists
every source adapter, target provider, and entry-point result (`loaded`, `failed`, or
`skipped`, with the owning distribution) and exits with code 1 when a plugin fails to load,
so it can gate a CI job. The repository's `plugin-entry-points` job does this with both
example plugins; see
[Validate your change](developer-contribution-guide.md#validate-your-change) to repeat it
locally.

## Consuming stateless CLIs from IDE extensions

Future developer tools such as a VS Code extension should invoke the lightweight stateless package entrypoints rather than embedding FastAPI or SQLite `RunService`:

```bash
etl-assess preview ./alteryx-workflows
etl-assess assess ./alteryx-workflows
etl-assess evidence ./alteryx-workflows
etl-fabric evaluate ./alteryx-workflows/sample_alteryx_workflow.yxmd
etl-fabric compile ./alteryx-workflows/sample_alteryx_workflow.yxmd --target dataflow
```

Both commands emit deterministic JSON over stdout and require only `etl-migration-core` plus the selected library wheel.
