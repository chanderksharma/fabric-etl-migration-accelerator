---
title: Release Notes v1.0.0
description: v1.0.0 capabilities plus unreleased modernization foundation and final-refactoring updates
ms.date: 2026-11-24
ms.topic: reference
---

**Release Date:** 2026-11-21  
**Asset Type:** Chrysalis IP Collection (`v1.0.0`)

## Summary

Chrysalis-ready InnerSource release of the **Microsoft Fabric ETL Migration Accelerator**, unifying deterministic multi-source ETL estate assessment, modular PyPI packages, compiler-grounded Microsoft Fabric artifact generation, Fabric-native FEMA analytics, and secretless CI/CD `dev` workspace deployment across **Alteryx Designer**, **Informatica PowerCenter**, and **Informatica IDMC**.

## Capabilities Included

- **Modular Multi-Package `uv` Workspace**:
  - `etl-migration-core`: Canonical `EtlPackage` IR, secure archive staging, built-in source adapters, and target SPI (`TargetPlatformRegistry` with fail-closed roadmap placeholders for `databricks`, `synapse`, and `snowflake`).
  - `etl-portfolio-assessment`: Target-neutral portfolio scoring, redacted graph evidence, and stateless `etl-assess` CLI.
  - `etl-target-fabric`: Microsoft Fabric evaluator, F-SKU capacity model, Dataflow Gen2 / PySpark / Data Pipeline compilers, artifact writer, and stateless `etl-fabric` CLI.
  - `fabric-etl-migration-accelerator`: FastAPI loopback server, SQLite WAL `RunService`, Typer `tool` CLI, CI dispatchers, wheel-backed local/desktop launchers (`Start-LocalApp.ps1`, `Build-Desktop.ps1`), and multi-stage wheel `Dockerfile`.
- **Multi-Source Discovery & Intake**: Recursive file, folder, `.yxzp`, and `.zip` ingestion with archive-bomb, symlink, and `defusedxml` entity/depth protections plus SHA-256 content deduplication.
- **7-Tab Analyst Workbench & 6-Tab Workflow Drawer**: React 19 UI separating assessment review (**Portfolio**, **Workflows**, **Migration Plan**, **Technical Details**, **Capacity Sizing**) from target-platform selection, Fabric code generation, and GitOps dispatch (**Fabric Deployment**).
- **Fabric-Native FEMA Workspace Stack**: One-step deployment (`Deploy-AcceleratorWorkspace.ps1` / `Deploy_FEMA.ipynb`) provisioning the Lakehouse, Runtime 2.0 Environment with the 3 decoupled library wheels, Assessment Notebook, 8 Delta tables, Direct Lake Semantic Model, 5-page Power BI leadership report, and Fabric Analyst App (`fema-etl-migration-app`).
- **Deterministic Target Compilers**:
  - **Dataflow Gen2 (`mashup.pq` + `queryMetadata.json`)**: Linear step folding, multi-source joins/unions/crosstabs, Alteryx `ToolContainer` → `queryGroups` hierarchy, PowerCenter Expression/Router/Aggregator compilation, and staging disabled (`allowFastCopy: false`, `loadEnabled: false`) by default.
  - **Fabric Notebook (`.ipynb`)**: Structured markdown guidance, source configuration table, PySpark stage transformations, and explicit `transform_bindings` hooks.
  - **Data Pipeline (`pipeline-content.json`)**: Automated `RefreshDataflow` → `TridentNotebook` orchestration bundles and IDMC taskflow compilation.
- **Dispatch-Only CI/CD with Entra OIDC**: GitHub Actions (`deploy-fabric-artifacts.yml`) and GitLab CI (`.gitlab-ci.yml`) deployment via `scripts/Deploy-FabricArtifacts.ps1` using Microsoft Entra Workload Identity Federation (OIDC), idempotent `Update` conflict handling, definition readback, and `executeQuery` validation.
- **SDL & Chrysalis Governance**: STRIDE threat model, CodeQL (`python`, `javascript-typescript`), `pip-audit --strict`, `npm audit --audit-level=high`, Dependabot, and 100% synthetic test fixtures.

## Validation Summary

- **Python (`3.13`)**: `262 passed` (`85.03%` line coverage), `ruff` 0 issues, `mypy --strict` 0 issues, `twine check` passed across all 4 wheels, and wheel-backed `Start-LocalApp.ps1 -VerifyOnly` + `Build-Desktop.ps1` smoke tests passed.
- **Web (`apps/web` — React 19 / TypeScript / Vite)**: `66 passed` (`vitest`), `eslint` 0 issues, and `vite build` clean.
- **Fabric Analyst App (`apps/etl-migration-assessment-app`)**: `206 passed | 1 skipped` (`vitest`), `eslint` 0 errors.

## Known Boundaries

- Generated definitions are `generated_unvalidated`; workspace-specific data connections, destination bindings, and semantic parity sign-off remain required before promotion beyond `dev`.
- Multi-mapping PowerCenter workflows and unsupported Alteryx macros/plugins intentionally emit non-deployable `scaffold` diagnostics for manual engineering completion.
- Microsoft Fabric currently blocks service-principal Dataflow refresh (`SPNBasedRefreshNotAllowed`); CI validates saved queries via `executeQuery` instead.

## Unreleased foundation follow-up

These changes are in the working tree on `feature/etl-modernization-foundation`.
They are not part of the v1.0.0 release above, and they are not a new version tag.

- Durable generation jobs and a candidate cache. Synchronous generate and preview stay synchronous. Jobs do not write artifact files, and neither the portal nor the CLI exposes them.
- A target-neutral `ArtifactSet` projection. Its `files` collection is empty. The Fabric disk writer is unchanged.
- Schema 7 appends `generation_jobs`, and schema 8 appends `runs.assessment_basis`. Existing state migrates forward. The schema-4 baseline is unchanged.
- Portfolio assessment is static and never runs a compiler. Fabric routing is confirmed in a separate fit stage (`POST /api/runs/{id}/targets/fabric/evaluate`, run automatically when **Fabric Deployment** opens and by every route that builds an artifact tree). Runs and exports report `routing_basis` (`static_mapping` or `compiler_confirmed`). Behavior changes to know before upgrading:
  - Fabric target, wave, effort, and capacity in a fresh run are the static mapping until confirmed. On the synthetic sample estate, 9 of 15 Alteryx workflows change when confirmed.
  - `tool assess` is static for every source. Before, Informatica results from `tool assess` were already compiler-routed. `etl-assess` is the target-neutral facade and is unchanged.
  - `FabricAssessmentApplication.assess(route_alteryx=...)` is now `route_native=...`, and it applies to every source. The old name still works. `FabricAssessmentApplication` moved to `etl_target_fabric.application`, and `etl_target_fabric.assessment.evaluator` and `.portfolio` still resolve to the relocated code.
  - Assessment exports keep their formats and add an `X-Routing-Basis` response header.
  - A run stored by an earlier release is served as stored.
- An optional SPI handshake. A missing `spi_version` means `1.0.0`. An incompatible declaration fails registration.
- Fail-closed generation. Missing linear Alteryx configuration scaffolds. Malformed Power Query M is not marked `generated_unvalidated`. One unexpected workflow fault becomes a blocked candidate and is not cached.
- A sample-estate golden digest for compiler output. It does not replace `generated-fabric-workflows/`.
- The **Fabric Deployment** page labels its code buttons **Generate Notebook code**, **Generate Dataflow code**, and **Generate Pipeline code** and says the results are not saved. They previously read "Generate ... previews", which suggested nothing was compiled. The buttons still compile the workflows and write to a temporary folder only.
- The **Installed plugins** option is removed from the portal's New Assessment page for now, because it was confusing. The intake offers **Alteryx** and **Informatica** only, and a selection that contains external-source assets is rejected with a message. Plugin discovery, `GET /api/sources`, `GET /api/plugins`, `tool plugins`, and the target-neutral workspace for runs created through the API are unchanged.
- The Fabric analyst app's **Source workflow graph** now matches the local web app's graph interaction model. It renders compact 72 by 42 source-coordinate SVG nodes and connections with support-state styling, search, zoom, fit, pan, keyboard selection, metadata details, a complete tool register, and a derived-layout fallback. Unbounded `ToolContainer` records remain in the register but are omitted from the canvas until the semantic model persists their width and height. The previous view flattened the first 12 nodes into a disconnected horizontal strip, and an interim larger-node version overlapped dense source layouts.
- The Fabric analyst app now keeps portfolio assessment separate from compiler-confirmed Fabric fit. Notebook assessment persists the input path, `RoutingBasis`, and remaining effort; **CI/CD dispatch** explicitly confirms fit in a separate notebook run before enabling manifest preview. Legacy runs without a basis are treated as already compiler-confirmed.
- Fabric intake now provides staged-scope confirmation, duplicate-content skipping, single-source-family validation, bounded batch limits, and active notebook cancellation. Portfolio leadership content fails closed while data is loading or unavailable.
- Fabric analyst exports now cover portfolio JSON plus workflow, migration, capacity, and technical CSV data with spreadsheet-formula defusing. Capacity assumptions and per-workflow overrides persist locally by run in the current browser.
- The Fabric app deployment page is now named **CI/CD dispatch**. It states that `generated-fabric-workflows` must already exist in the selected repository/ref; the Fabric app validates and dispatches those artifacts but does not generate them.
- **CI/CD dispatch** now always shows the provider-specific **Trigger GitHub Actions** or **Trigger GitLab CI** button. A readiness checklist explains every unmet prerequisite instead of silently disabling **Preview manifest** and hiding the trigger. The trigger remains disabled until manifest validation and explicit review confirmation succeed.
- Added `scripts/Deploy-FabricAssessmentStack.ps1` for environments where the three decoupled wheels are already built. It validates the wheel set and deploys only the Lakehouse, Runtime 2.0 Environment, assessment Notebook, eight Delta tables, Direct Lake Semantic Model, and Power BI Report. It deliberately skips wheel building and the Fabric Analyst App.

Plugin target deployment dispatch to live CI remains Fabric-wired. A full Alteryx-to-IR compiler unification, process-pool parallelism, out-of-process plugins, Entra OIDC RBAC, and a PostgreSQL backend remain deferred.

## Unreleased refactoring & hardening (`feature/final-refactoring`)

These changes build on the foundation follow-up above on `feature/final-refactoring`:

- **Server-mode & container hardening**: Added `ACCELERATOR_MODE` (`local` | `desktop` | `server`), dynamic `ACCELERATOR_ALLOWED_HOSTS` (with `*.domain` wildcards), `ACCELERATOR_ALLOW_LOCAL_FILESYSTEM`, and fail-closed `ACCELERATOR_API_TOKEN` Bearer auth in `server` mode. Hardened `Dockerfile` with non-root `USER accelerator`, `HEALTHCHECK` against `/health`, and secure `server` defaults.
- **Input, XML & Fabric REST hardening**:
  - `IdmcExportClient` now streams downloads to temporary files with bounded chunk reads, on-disk zip-bomb checks (entry count, uncompressed ceiling, compression ratio), validated/URL-encoded `job_id`, and loopback/private IP blocking.
  - Replaced stdlib `xml.etree.ElementTree.fromstring` in `compilers/alteryx.py` and `capacity/model.py` with `defusedxml`.
  - Hardened `scripts/FabricApi.psm1` to enforce `https://api.fabric.microsoft.com` origin checks on HTTP 202 LRO `Location` polling headers, validate `x-ms-operation-id`, enforce `TimeoutSec = 60`, cap `Retry-After` at `60 s`, and truncate error bodies.
- **Assessment parity & core boundary cleanup**:
  - `ir_assessment.py` now excludes `node.disabled` nodes/edges and classifies `node.issues` as `"manual"` (`ASSESSMENT_RULES_VERSION = "1.4.1"`, golden digest refreshed).
  - Moved `m_literals.py` from `etl-migration-core` to `etl-target-fabric/compilers/m_literals.py`; consolidated shared discovery schemas into `etl-migration-core/intake/schemas.py` and archive helpers into `intake/archive.py`; added pluggable `SourceArchiveDiscoveryAdapter`, `SourceDirectoryDiscoveryAdapter`, and `SourceParseError`; widened `NeutralWorkloadProfile.profile_kind`.
  - Fixed `FabricAssessmentApplication` to reuse an injected `DiscoveryService` registry and added per-file fault isolation to `PortfolioAssessmentApplication.inspect_evidence`.
- **Runtime decomposition, observability & storage boundary**:
  - Extracted `SnapshotManager` (with per-item verification on single-workflow `workflow_candidates` and `evidence` reads), `CapacityService`, `PublicationService`, and parallel `TargetOrchestrator` from `RunService`.
  - Added `RunStoreProtocol`, paginated `GET /api/runs?limit=&offset=`, `GET /livez`, `GET /readyz`, `X-Request-ID` propagation, structured JSON logging (`ACCELERATOR_LOG_FORMAT=json`), event-driven worker wakeups with `ACCELERATOR_WORKER_CONCURRENCY`, optional `write_plan=false` on `/generate`, and unified `CiDeploymentDispatcher` (`delivery/base.py`).
- **Enriched Alteryx IR, Expression AST & complete Target SPI**:
  - `AlteryxSourceAdapter` now populates structured `EtlNode.properties["parsed_config"]`; added `build_alteryx_ir_capacity_profile` and wired `FabricTargetCapacityEstimator` to model Alteryx IR packages directly.
  - Added deterministic shared `etl_target_fabric/compilers/expr_ast.py` and extracted `delivery/notebook_encoder.py`.
  - Completed Target SPI protocols (`TargetValidatorProvider`, `TargetDryRunProvider`, `TargetDeploymentProvider`), implemented `FabricTargetProvider.dry_run_planner()`, added capability-driven codegen previews to `NeutralWorkspace.tsx`, and added `tests/test_openapi_contract.py`.
- **CI parity & dependency cleanup**: Updated `azure-pipelines.yml` to lint `src packages tests examples` and run isolated wheels, plugin entry points, script syntax checks, and `pip-audit`/`npm audit`; added `scripts` and `linux-container` jobs to `.github/workflows/ci.yml`; removed unused dev dependencies (`ipykernel`, `ipywidgets`, `tqdm`) reducing `uv.lock` from 98 to 66 packages, plus dead files/helpers (`desktop/entry.py`, `etl_target_fabric/assessment/effort.py`, `_node_name`, `_current_fabric_fit`).
- **Verification**: `464 passed` Python tests (`87.33%` coverage), `ruff` + `mypy --strict` 0 issues across 143 files, `83 passed` React tests (`apps/web`), isolated wheel + plugin entry-point E2E (`synthetic-ssis` → `synthetic-databricks`), live server + multi-source (Alteryx + PowerCenter + IDMC) + publication E2E, and PowerShell `Deploy-FabricArtifacts.ps1 -DryRun` + `Assert-DeploymentPublication.ps1` interop verified.
