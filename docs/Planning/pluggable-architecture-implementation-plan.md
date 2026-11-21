---
title: Pluggable Architecture Implementation Plan
description: Modular, portable, and pluggable implementation plan for decoupling ETL portfolio assessment, target-platform providers, PyPI packages, and runtime hosts with strict separation of duties
ms.date: 2026-11-21
ms.topic: reference
---

## Objective and scope

This plan defines the incremental engineering roadmap to transform the single-package `fabric-etl-migration-accelerator` monolith into a modular, portable, and pluggable multi-package architecture with strict separation of duties. It aligns with [Figure ARCH-02](../Architecture/arch-02-pluggable-solution-architecture.vsdx.fig.png), [Pluggable Architecture Business Requirements](./pluggable-architecture-business-requirements.md), and [Pluggable Architecture Analysis and Target Approach](./pluggable-architecture-analysis-and-approach.md).

Key engineering outcomes:

* Separate canonical ETL IR and source parsing, target-neutral portfolio assessment, and target-platform providers into independently installable PyPI packages
* Eliminate circular dependencies and target-platform leakage across assessment, capacity modeling, routing, and code generation
* Introduce a versioned Target Platform Service Provider Interface (SPI) and registry supporting Microsoft Fabric alongside fail-closed placeholder registrations for Databricks, Azure Synapse, and Snowflake
* Preserve full backward compatibility for existing Alteryx and Informatica users, FastAPI routes, Typer CLI commands, React UI, Fabric Analyst App, and FEMA workspace deployment

## Separation of duties and dependency rules

Every module in the target architecture belongs to exactly one responsibility layer. Dependencies flow strictly downward toward the core IR kernel, with zero upward or sibling cross-imports.

| Layer | Responsibility | Must NOT contain | Allowed dependencies |
| :--- | :--- | :--- | :--- |
| Canonical IR and Source SPI (`etl-migration-core`) | Secure file/archive staging, `EtlPackage` / `EtlGraph` / `EtlAsset` schemas, SPI protocols, entry-point discovery, source adapters | Fabric component names, F-SKUs, target code generators, SQLite, FastAPI, Typer | `pydantic`, `defusedxml` |
| Portfolio Assessment (`etl-portfolio-assessment`) | Source-neutral inventory, dependency DAG, complexity score, source risk, wave inputs, redacted evidence, workload profile | Dataflow/Notebook/Pipeline classifications, Fabric F-SKUs, Databricks DBUs, code emitters | `etl-migration-core` |
| Target Platform Providers (`etl-target-*`) | Target-fit evaluation, target capacity sizing, code compilation, artifact serialization, static validation, dry-run and deploy | Source file parsing, SQLite `RunService`, React UI, GitHub/GitLab dispatch logic | `etl-migration-core`, optional assessment contract types |
| Delivery Channels | GitHub Actions, GitLab CI, and Azure DevOps workflow dispatch and status mapping | Target-platform syntax, artifact compilation, source parsing | `pydantic`, `pyjwt` |
| Application Shell (`accelerator`) | SQLite WAL `RunService`, FastAPI loopback server, Typer CLI, Windows Desktop (`pywebview`), compatibility shims | Direct XML parsing heuristics or platform-specific compiler internals | Core packages + `fastapi`, `uvicorn`, `typer` |
| Serving Consumers | React Portfolio UI, Fabric Analyst App + Power BI, Fabric Runtime 2.0 Notebook, future VS Code Developer Extension | Duplicate Python parsers or compilers in TypeScript or DAX | HTTP API, Delta/Direct Lake, or stateless stdio JSON-RPC |

> [!IMPORTANT]
> Target platform identity must be modeled as an open `str` identifier (for example `"fabric"`, `"databricks"`, `"synapse"`, `"snowflake"`) rather than a closed `StrEnum`. Closed enumerations prevent third-party PyPI provider wheels from registering without modifying central packages.

## Target `uv` workspace and PyPI package topology

Keep a single Git repository managed as a `uv` workspace with Hatchling build backends. A monorepo preserves atomic IR evolution and unified CI checks while building independent `.whl` artifacts per package.

```text
fabric-etl-migration-accelerator/
|-- pyproject.toml                            # Root workspace + accelerator app shell
|-- uv.lock                                   # Unified workspace lockfile
|-- packages/
|   |-- etl-migration-core/                   # PyPI: etl-migration-core
|   |   |-- pyproject.toml                    # Deps: pydantic, defusedxml
|   |   |-- README.md
|   |   |-- src/etl_migration_core/
|   |   |   |-- py.typed
|   |   |   |-- contracts/                    # ir.py (EtlPackage IR), spi.py (Protocols)
|   |   |   |-- intake/                       # domain.py, discovery.py (secure staging & zip guards)
|   |   |   |-- sources/                      # Built-in Alteryx, PowerCenter, IDMC + registry/defaults
|   |   |   `-- targets/                      # TargetPlatformRegistry + roadmap placeholders
|   |   `-- tests/
|   |-- etl-portfolio-assessment/             # PyPI: etl-portfolio-assessment
|   |   |-- pyproject.toml                    # Deps: etl-migration-core
|   |   |-- README.md
|   |   |-- src/etl_portfolio_assessment/
|   |   |   |-- py.typed
|   |   |   |-- assessment/                   # engine.py, effort.py, workload_profile.py
|   |   |   |-- evidence/                     # extractor.py (redacted bounded graph evidence)
|   |   |   `-- service/                      # application.py, schemas.py, stdio.py (etl-assess CLI)
|   |   `-- tests/
|   `-- etl-target-fabric/                    # PyPI: etl-target-fabric
|       |-- pyproject.toml                    # Deps: etl-migration-core
|       |-- README.md                         # Entry-point: etl_migration.targets = fabric
|       |-- src/etl_target_fabric/
|       |   |-- py.typed
|       |   |-- provider.py                   # FabricTargetProvider implementing Target SPI
|       |   |-- stdio.py                      # Stateless etl-fabric CLI
|       |   |-- assessment/                   # support_matrix.py, evaluator.py, portfolio.py, effort.py, schemas.py
|       |   |-- capacity/                     # model.py (Fabric F2-F8192 & CU sizing)
|       |   |-- compilers/                    # alteryx.py, ir.py (Dataflow M, PySpark, Pipeline)
|       |   `-- delivery/                     # artifact_writer.py, deployer.py
|       `-- tests/
|-- src/accelerator/                          # App shell (server/, cli/, runtime/, delivery/, desktop/, targets/)
|-- apps/                                     # React UI (apps/web) & Rayfin Fabric Analyst App
|-- notebooks/                                # Headless Spark assessment & FEMA installer
`-- scripts/                                  # PowerShell & Node deployment, wheel-app, & desktop automation
```

> [!NOTE]
> Package names (`etl-migration-core`, `etl-portfolio-assessment`, `etl-target-fabric`) must be checked for availability on the target package index before publishing. Internal Microsoft distribution via Azure Artifacts supports the existing Microsoft Internal license immediately, whereas public PyPI distribution requires Legal and Open Source Programs Office (OSPO) approval and an OSI-approved license.

## Current-to-target module migration map

All 34 existing Python modules under `src/accelerator/` map cleanly without duplicating logic.

| Current module | Target destination | Refactoring required |
| :--- | :--- | :--- |
| `etl_ir.py` | `etl_migration_core.ir` | Remove any Fabric assumptions; keep pure Pydantic IR models and `IR_VERSION` |
| `domain.py` | `etl_migration_core.domain` | Keep `DiscoveryLimits`, `SkipReason`, `WorkflowCandidate` |
| `discovery.py` | `etl_migration_core.discovery` | Remove direct import of `PowerCenterSourceAdapter`; delegate multi-asset XML splitting to the registered source adapter |
| `idmc_export.py` | `etl_migration_core.sources.informatica_idmc.client` | Move alongside IDMC adapter so the IR kernel stays free of HTTP client logic |
| `sources/` | `etl_migration_core.sources` | Add `importlib.metadata` entry-point loading (`etl_migration.sources`) alongside built-in defaults |
| `graph.py` | `etl_migration_core.sources.alteryx.graph` | Keep XML graph parsing scoped inside the Alteryx adapter once Alteryx unifies onto `EtlPackage` |
| `assessment.py`, `etl_assessment.py` | Split across `etl_portfolio_assessment` and `etl_target_fabric` | Extract target-neutral scoring into `etl_portfolio_assessment.engine`; move `DATAFLOW_*`, `NOTEBOOK_*`, and `PIPELINE_*` markers into `etl_target_fabric.support_matrix` |
| `capacity.py` | Split across `etl_portfolio_assessment` and `etl_target_fabric` | Extract neutral `WorkloadProfile` (operator counts, schedule interval); keep `SKU_TIERS`, `FABRIC_COMPONENTS`, and CU math in `etl_target_fabric.capacity` |
| `effort.py` | Split across `etl_portfolio_assessment` and `etl_target_fabric` | Keep `practical_effort_days` / base source effort in assessment; move binding-driven `remaining_effort_days` into target evaluation |
| `evidence.py` | `etl_portfolio_assessment.evidence` | Remove private `_support_for` imports from assessment; emit neutral node classification plus optional provider overlay |
| `schemas.py` | Split by domain | Keep neutral `DiscoverySummaryResponse` and neutral assessment schemas in `etl_portfolio_assessment`; move Fabric target fields into provider evaluation schemas and app DTO adapters |
| `application.py` | `etl_portfolio_assessment.application` | Decouple from `etl_routing.py` via an optional `TargetEvaluator` hook injected by callers |
| `generation.py`, `etl_generation.py` | `etl_target_fabric.generators` | Unify Alteryx compilation onto `EtlPackage` / `EtlGraph` or encapsulate Alteryx legacy compiler inside `etl_target_fabric` without importing `assessment.py` |
| `etl_routing.py` | `etl_target_fabric.evaluator` | Return a pure `TargetEvaluation` result instead of mutating `WorkflowAssessment` or `EtlAssessment` dataclasses |
| `deployment.py` | `etl_target_fabric.deployer` | Implement `TargetDeployer` protocol for Fabric dry-run planning |
| `runs.py` (artifact emission) | `etl_target_fabric.artifact_writer` | Extract `_artifact_path`, manifest creation, and disk serialization (`write_candidates`) out of SQLite `RunService` |
| `runs.py` (WAL store), `api.py`, `cli.py`, `desktop.py`, `desktop_entry.py` | `accelerator` (root app shell) | Orchestrate registries, SQLite runs, REST routes, CLI, and Desktop shell; keep temporary `accelerator.*` re-export shims for legacy imports |
| `github_deployment.py`, `gitlab_deployment.py` | `accelerator.delivery` | Formalize behind a `DeliveryChannel` protocol independent of Fabric target details |

## Service Provider Interface (SPI) and placeholder design

Define minimal, runtime-verifiable protocols inside `etl_migration_core.spi` so source adapters, neutral assessment, and target providers compose cleanly without tight coupling.

```python
from pathlib import Path
from typing import Protocol, runtime_checkable

@runtime_checkable
class TargetPlatformProvider(Protocol):
    @property
    def platform_id(self) -> str: ...          # e.g. "fabric", "databricks", "synapse", "snowflake"
    @property
    def display_name(self) -> str: ...
    @property
    def provider_version(self) -> str: ...
    @property
    def supported_ir_versions(self) -> tuple[str, ...]: ...
    @property
    def implemented(self) -> bool: ...          # False for roadmap placeholders
    @property
    def capabilities(self) -> tuple[str, ...]: ...  # e.g. ("evaluate", "capacity", "codegen", "dry_run")

    def evaluator(self) -> TargetEvaluator | None: ...
    def capacity_estimator(self) -> CapacityEstimator | None: ...
    def generator(self) -> CodeGenerator | None: ...
    def validator(self) -> ArtifactValidator | None: ...
    def deployer(self) -> TargetDeployer | None: ...
```

### Rules for placeholder providers (Databricks, Azure Synapse, Snowflake)

1. Built-in placeholder registrations (`databricks`, `synapse`, `snowflake`) implement `TargetPlatformProvider` with `implemented = False`, `capabilities = ()`, and `None` returned for all operational hooks.
2. Any attempt to evaluate, estimate capacity, generate code, or plan deployment against an unimplemented placeholder must fail closed by raising a typed `UnsupportedTargetCapabilityError` or returning a non-deployable diagnostic record stating that the provider is a roadmap placeholder.
3. Placeholders must never emit fake SQL, fake PySpark templates, or uncalibrated DBU, DWU, or credit estimates (`ADR-L04` and `ADR-L08`).
4. When a dedicated package such as `etl-target-databricks` is installed via `pip` or `uv`, `TargetPlatformRegistry` resolves the `importlib.metadata` entry point (`etl_migration.targets`) and supersedes the built-in placeholder for that `platform_id` deterministically.
5. Keep Azure Synapse strictly as a lightweight optional placeholder target. In most Fabric modernization engagements, Synapse Dedicated SQL Pool and Synapse Spark act as source estates migrating into Fabric rather than greenfield destinations.

## Phased delivery plan

### Phase 0: Baseline freeze and governance alignment

Goal: Establish immutable regression guardrails and resolve package distribution governance before refactoring.

Deliverables:

1. Verify current full validation baseline passes (`ruff`, `mypy --strict`, `pytest --cov-fail-under=80`, `apps/web` lint/test/build).
2. Add golden snapshot tests covering Alteryx, PowerCenter, and IDMC assessment outputs, Fabric capacity outputs, and generated Dataflow/Notebook/Pipeline artifacts so refactoring preserves byte-level or schema-level parity.
3. Confirm target PyPI distribution channel (internal Microsoft Azure Artifacts PyPI feed vs public PyPI with OSPO/Legal clearance) and reserve package names.

Exit criteria:

* Baseline golden fixtures committed using synthetic corpus only
* Distribution feed and Python version floor decision recorded (`>=3.13` for Fabric Runtime 2.0 vs `>=3.11` / `>=3.12` for broader developer CLI/IDE portability)

### Phase 1: Break internal coupling inside `src/accelerator`

Goal: Enforce separation of duties inside the existing package without changing external APIs, CLI commands, or wheel packaging.

Work items:

1. Unify Alteryx onto Canonical IR by routing Alteryx assessment and evidence through `AlteryxSourceAdapter.parse()` (`EtlPackage`) as the primary internal representation, preserving `WorkflowAssessment` and legacy `_artifact_path` outputs through thin compatibility adapters (`ADR-001` and `tests/test_compatibility_contract.py`).
2. Decouple `discovery.py` by replacing the direct `PowerCenterSourceAdapter` import with an adapter capability hook on `SourceAdapterRegistry` for multi-asset file expansion.
3. Separate neutral workload profiling from Fabric capacity by extracting `WorkloadProfile` (platform-agnostic operator counts and schedule intervals) from `capacity.py`, leaving `SKU_TIERS`, `FABRIC_COMPONENTS`, and CU math in a Fabric-specific module.
4. Break the `etl_routing.py` cycle by removing cross-imports between `assessment.py` / `etl_assessment.py` and `generation.py` / `etl_generation.py`, having Fabric evaluation return a `TargetEvaluation` object that leaves the neutral assessment immutable.
5. Extract `ArtifactWriter` from `runs.py` by moving `_artifact_path`, manifest serialization, and disk file generation (`write_artifacts`) into a stateless module independent of SQLite `RunService`.
6. Separate delivery channels by defining a `DeliveryChannel` protocol over `github_deployment.py` and `gitlab_deployment.py` so `api.py` dispatches through one interface.

Exit criteria:

* Zero imports from Fabric codegen or capacity modules inside neutral assessment modules
* Zero imports from `assessment.py` inside `generation.py` or `etl_generation.py`
* All existing tests, including `tests/test_compatibility_contract.py`, pass without modification to public API contracts

### Phase 2: Target Platform SPI, registry, and roadmap placeholders

Goal: Introduce `TargetPlatformRegistry` and register Microsoft Fabric alongside fail-closed placeholders for Databricks, Azure Synapse, and Snowflake.

Work items:

1. Define `spi.py` protocols (`SourceAdapter`, `TargetPlatformProvider`, `TargetEvaluator`, `CapacityEstimator`, `CodeGenerator`, `ArtifactValidator`, `TargetDeployer`, `DeliveryChannel`).
2. Implement `TargetPlatformRegistry` supporting deterministic static registration plus `importlib.metadata.entry_points(group="etl_migration.targets")`, version compatibility checks (`IR_VERSION`), and placeholder override rules when an external plugin wheel is installed.
3. Implement `FabricTargetProvider` wrapping the refactored Fabric evaluator, `capacity.py`, Dataflow/Notebook/Pipeline generators, `ArtifactWriter`, and `dry_run`.
4. Implement metadata-only, fail-closed `PlaceholderTargetProvider` entries for `"databricks"`, `"synapse"`, and `"snowflake"`.
5. Expose read-only target catalog endpoints (`GET /api/targets`) and CLI listing (`tool targets`) returning each provider's `platform_id`, `display_name`, `implemented` flag, and `capabilities`.
6. Update `api.py` and `RunService` to store neutral assessment results alongside a separate target-evaluation dictionary keyed by `platform_id` while preserving legacy flattened fields on existing endpoints during deprecation.

Exit criteria:

* Adding a mock external target provider in tests works via registry injection and `entry_points` without editing source adapters, assessment engine, or FastAPI routes
* Invoking evaluation, capacity, or codegen on `"databricks"`, `"synapse"`, or `"snowflake"` fails closed with structured diagnostics and produces zero runnable artifacts

### Phase 3: Split into `uv` workspace PyPI packages and portable interfaces

Goal: Extract the decoupled modules into independent Python packages with strict dependency boundaries and stateless single-asset portability.

Work items:

1. Configure `pyproject.toml` at the repository root as a `[tool.uv.workspace]` managing `packages/etl-migration-core`, `packages/etl-portfolio-assessment`, `packages/etl-target-fabric`, and the root `fabric-etl-migration-accelerator` app package.
2. Add `py.typed`, package-level `README.md`, license metadata, classifiers, and explicit version bounds (`etl-migration-core>=1.0.0,<2.0.0`) to each library `pyproject.toml`.
3. Provide stateless single-asset CLI/Python functions and a minimal stdio JSON-RPC entrypoint (`inspect`, `assess`, `compile`, `evidence`) in the libraries with zero dependency on SQLite, FastAPI, or Typer, enabling portable execution in CI containers, notebooks, and future VS Code developer extensions.
4. Preserve temporary re-export shims under `src/accelerator/` with `DeprecationWarning` notices so existing imports in downstream scripts remain functional across one major/minor cycle.
5. Configure per-package isolated test matrices in `.github/workflows/ci.yml` so each wheel installs and passes tests in an isolated virtualenv without sibling or app packages installed (`etl-portfolio-assessment` tested without `etl-target-fabric` or `fastapi`).

Exit criteria:

* `uv build --all-packages` produces valid wheels for all packages
* Isolated `pytest` runs prove `etl-migration-core` and `etl-portfolio-assessment` work with only `pydantic` and `defusedxml` installed
* `etl-target-fabric` passes compiler and capacity tests with zero dependency on `fastapi`, `uvicorn`, `typer`, `pyjwt`, or `runs.py`

### Phase 4: FEMA Fabric deployment and notebook modernization

Goal: Slim down the Microsoft Fabric Runtime 2.0 environment and deploy the decoupled wheels cleanly into Fabric workspaces.

Work items:

1. Remove `fastapi`, `uvicorn`, `typer`, `pyjwt[crypto]`, `python-dotenv`, and `python-multipart` from `scripts/fabric-environment.yml`, keeping only core runtime requirements.
2. Update `scripts/Deploy-AcceleratorWorkspace.ps1`, `scripts/build-fema-bundle.mjs`, and `notebooks/Deploy_FEMA.ipynb` to build, stage, and upload the separated library wheels (`etl_migration_core`, `etl_portfolio_assessment`, `etl_target_fabric`) into `ETL_Migration_Assessment_Env`, or reference them directly from the published PyPI/Artifacts feed.
3. Update `notebooks/fabric-portfolio-assessment.ipynb` to import from the decoupled library APIs (`etl_migration_core`, `etl_portfolio_assessment`, `etl_target_fabric`), keeping Delta Lake persistence and automatic Direct Lake refresh intact.
4. Add unit and integration checks in `tests/test_fema_deployment.py` verifying multi-wheel bundle packaging and Spark environment dependency hygiene.

Exit criteria:

* `build-fema-bundle.mjs --require-wheel` packages all required wheels deterministically
* `Deploy-AcceleratorWorkspace.ps1` and live `fabric-dev` deployment succeed with the slimmed Runtime 2.0 environment and refresh the Direct Lake Power BI report

### Phase 5: PyPI publishing automation and future extension readiness

Goal: Automate trusted package releases and prepare onboarding templates for future providers and IDE clients.

Work items:

1. Create `.github/workflows/publish-packages.yml` triggered on release tags (`v*`) to build all workspace distributions, run `twine check`, smoke-test each wheel in a fresh venv, and publish using OIDC Trusted Publishing (`pypa/gh-action-pypi-publish`) or Azure Artifacts OIDC.
2. Document the Source Adapter and Target Provider SDK contract (`docs/Guides/building-plugins.md`), including a template for external `etl-target-databricks` and `etl-source-*` packages.
3. Verify readiness prerequisites for future extensions:
   * Node-to-code provenance (`SourceLocation` + `native_id`) retained in compiled outputs for future VS Code CodeLens and diff navigation
   * Stateless stdio JSON-RPC worker contract documented for thin IDE extensions
   * `docs/Architecture/system-architecture.md` and `README.md` updated with final package installation instructions

Exit criteria:

* End-to-end release dry run succeeds against TestPyPI or internal Artifacts feed
* Both `pip install etl-portfolio-assessment` and `pip install etl-target-fabric` execute verified smoke tests in clean environments

## Portability and security controls

| Dimension | Architectural control | Verification mechanism |
| :--- | :--- | :--- |
| Runtime portability | Core packages depend only on Python stdlib, `pydantic`, and `defusedxml`; zero OS-specific or FastAPI/SQLite coupling | Isolated `uv run --isolated --with <wheel>` smoke tests on Windows and Linux |
| Spark and Fabric portability | `scripts/fabric-environment.yml` omits web/auth server packages; notebooks use pure Python APIs without local DB state | `tests/test_fema_deployment.py` and live Fabric Runtime 2.0 execution |
| Python version compatibility | Align `requires-python` across library packages (`>=3.13` for Fabric Runtime 2.0 parity, or lower core libraries to `>=3.11` if desktop/IDE adoption requires it) | `tests/test_project_configuration.py` and CI matrix |
| Security and non-AI core | Preserve `defusedxml` DTD/entity limits, ZIP-bomb caps, zero workflow expression execution, and zero LLM calls inside parser/compiler packages | `CodeQL`, `pip-audit`, `tests/test_discovery.py`, threat model checks |
| Fail-closed safety | Unimplemented targets (`databricks`, `synapse`, `snowflake`) and unsupported transforms emit diagnostics only and never produce runnable deployment envelopes | Provider contract tests (`tests/test_targets.py`) |

## Verification gate across all phases

Run the complete validation suite before merging any phase PR:

```powershell
uv run --extra dev ruff check src packages tests
uv run --extra dev mypy
uv run --extra dev pytest --cov-fail-under=80
node .\scripts\build-fema-bundle.mjs --require-wheel
```

For UI and Fabric Analyst App changes, also execute:

```powershell
cd apps\web; npm run lint; npm test; npm run build
cd ..\etl-migration-assessment-app; npm run lint; npm test
```

## Key design decisions to confirm before Phase 1

1. Confirm the package distribution target between an internal Azure Artifacts PyPI feed (compatible with the current Microsoft Internal `LICENSE`) and public PyPI (requiring OSPO/Legal sign-off and an OSI license change).
2. Decide the library Python version floor: keep `>=3.13` everywhere to match Fabric Runtime 2.0, or lower `etl-migration-core` and `etl-portfolio-assessment` to `>=3.11` for broader developer workstation and future VS Code extension compatibility.
3. Confirm the package naming prefix (`etl-migration-*` and `etl-target-*`, `fema-*`, or `fabric-etl-*`) based on target feed availability.
4. Set the deprecation window for `src/accelerator/` compatibility re-exports and flattened `WorkflowAssessmentResponse` fields after Phase 3.
