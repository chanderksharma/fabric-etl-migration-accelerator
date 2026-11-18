---
title: Release Notes v1.0.0
description: Initial release capabilities, validation evidence, and known boundaries
ms.date: 2026-11-17
ms.topic: reference
---

**Release Date:** 2026-11-15  
**Asset Type:** Chrysalis IP Collection (`v1.0.0`)

## Summary

Initial Chrysalis-ready InnerSource release of the **Microsoft Fabric ETL Migration Accelerator**, unifying deterministic multi-source ETL estate assessment, compiler-grounded Microsoft Fabric artifact generation, and secretless CI/CD `dev` workspace deployment across **Alteryx Designer**, **Informatica PowerCenter**, and **Informatica IDMC**.

## Capabilities Included

- **Multi-Source Discovery & Intake**: Recursive file, folder, `.yxzp`, and `.zip` ingestion with archive-bomb, symlink, and `defusedxml` entity/depth protections plus SHA-256 content deduplication.
- **Canonical ETL Graph & Portfolio UI**: Six-tab React 19 workflow inspection drawer (source canvas geometry, tool/endpoint registers, generated code preview, readiness diagnostics, and one-click bundle export) backed by resumable SQLite WAL runs.
- **Deterministic Target Compilers**:
  - **Dataflow Gen2 (`mashup.pq` + `queryMetadata.json`)**: Linear step folding, multi-source joins/unions/crosstabs, Alteryx `ToolContainer` → `queryGroups` hierarchy, PowerCenter Expression/Router/Aggregator compilation, and staging disabled (`allowFastCopy: false`, `loadEnabled: false`) by default.
  - **Fabric Notebook (`.ipynb`)**: Structured markdown guidance, source configuration table, PySpark stage transformations, and explicit `transform_bindings` hooks.
  - **Data Pipeline (`pipeline-content.json`)**: Automated `RefreshDataflow` → `TridentNotebook` orchestration bundles and IDMC taskflow compilation.
- **Dispatch-Only CI/CD with Entra OIDC**: GitHub Actions (`deploy-fabric-artifacts.yml`) and GitLab CI (`.gitlab-ci.yml`) deployment via `scripts/Deploy-FabricArtifacts.ps1` using Microsoft Entra Workload Identity Federation (OIDC), idempotent `Update` conflict handling, definition readback, and `executeQuery` validation.
- **SDL & Chrysalis Governance**: STRIDE threat model, CodeQL (`python`, `javascript-typescript`), `pip-audit --strict`, `npm audit --audit-level=high`, Dependabot, and 100% synthetic test fixtures.

## Validation Summary

- **Python (`3.13`)**: `165 passed` (`87.24%` line coverage), `ruff` 0 issues, `mypy --strict` 0 issues, `pip-audit --strict` 0 vulnerabilities.
- **Web (`Node 22` / `React 19` / `TypeScript 7.0.2`)**: `44 passed` (`vitest 5.1.0`), `eslint` 0 issues, and `vite build` clean.

## Known Boundaries

- Generated definitions are `generated_unvalidated`; workspace-specific data connections, destination bindings, and semantic parity sign-off remain required before promotion beyond `dev`.
- Multi-mapping PowerCenter workflows and unsupported Alteryx macros/plugins intentionally emit non-deployable `scaffold` diagnostics for manual engineering completion.
- Microsoft Fabric currently blocks service-principal Dataflow refresh (`SPNBasedRefreshNotAllowed`); CI validates saved queries via `executeQuery` instead.
