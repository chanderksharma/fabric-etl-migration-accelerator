---
title: Building Source and Target Plugins
description: Developer guide for extending etl-migration-core with custom source adapters, target platform providers, and stateless IDE integrations
ms.date: 2026-11-21
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

### Implement the provider protocol

```python
from collections.abc import Sequence
from pathlib import Path

from etl_migration_core.contracts.ir import IR_VERSION, EtlAsset, EtlPackage
from etl_migration_core.contracts.spi import (
    TargetCapability,
    TargetEvaluation,
    TargetEvaluator,
    TargetPlatformInfo,
)


class DatabricksEvaluator:
    def evaluate_alteryx_path(
        self,
        path: Path,
        *,
        unsupported_tools: Sequence[str],
        default_target: str,
        default_components: Sequence[str],
        default_reason: str,
    ) -> TargetEvaluation:
        return TargetEvaluation(
            platform_id="databricks",
            implemented=True,
            recommended_target="Databricks Workflow",
            target_components=("PySpark Notebook", "Databricks Job"),
            recommendation_reason=default_reason,
        )

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

## Adding a source adapter plugin

Source adapters normalize native ETL exports (such as SSIS `.dtsx`, Talend, or DataStage) into `EtlPackage` and register under the `etl_migration.sources` entry-point group.

These formats are extension examples, not current built-in support. A new
adapter also needs compatible source-platform contracts, secure discovery,
assessment, and runtime integration. See the
[developer contribution guide](developer-contribution-guide.md#extend-a-source-system).

```toml
[project.entry-points."etl_migration.sources"]
ssis = "etl_source_ssis.adapter:SsisSourceAdapter"
```

Keep source adapters strictly free of target-platform constructs (`Dataflow`, `Databricks`, `F-SKU`). Always parse untrusted XML using `defusedxml` with external entity expansion disabled, and never execute embedded workflow scripts.

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
