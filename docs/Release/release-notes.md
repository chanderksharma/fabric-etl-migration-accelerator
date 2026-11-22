---
title: Release Notes v1.0.0
description: v1.0.0 capabilities plus the unreleased modernization foundation follow-up
ms.date: 2026-11-22
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
- Schema 7 appends `generation_jobs`. Existing state migrates forward. The schema-4 baseline is unchanged.
- An optional SPI handshake. A missing `spi_version` means `1.0.0`. An incompatible declaration fails registration.
- Fail-closed generation. Missing linear Alteryx configuration scaffolds. Malformed Power Query M is not marked `generated_unvalidated`. One unexpected workflow fault becomes a blocked candidate and is not cached.
- A sample-estate golden digest for compiler output. It does not replace `generated-fabric-workflows/`.

Plugin target generation and deployment remain unwired. A compiler split, process-pool parallelism, out-of-process plugins, authenticated server mode, and a new database remain deferred. GitHub Actions and a live Fabric deployment were not run for this follow-up. A local portal check covered health, assessment, synchronous generate, one notebook generation job, publication download, and malformed-workflow isolation.
