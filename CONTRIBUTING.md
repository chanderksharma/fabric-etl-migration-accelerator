---
title: Contributing to Microsoft Fabric ETL Migration Accelerator
description: Development workflow, toolchain, security guardrails, and contribution requirements
---

Thank you for contributing to the **Microsoft Fabric ETL Migration Accelerator**. This project follows Microsoft **InnerSource** practices as defined by Chrysalis.

For step-by-step bug fixes, features, and source or target extensions, see the
[Developer Contribution Guide](docs/Guides/developer-contribution-guide.md).

---

## Introduction

Contributions are organized around three stakeholder groups:

1. **Core Team Members (Maintainers)** — Responsible for architectural stewardship, maintaining compiler determinism and security boundaries, welcoming and mentoring contributors, triaging issues, and reviewing pull requests (`CODEOWNERS`).
2. **Project Contributors** — Microsoft engineers, consultants, and architects contributing documentation refinements, bug fixes, new source-adapter parsers, Alteryx/Informatica transformation mappings, UI improvements, or Fabric deployment automation.
3. **Project Consumers** — Delivery teams using the accelerator on assessments or migrations who contribute back defect reports, unsupported-tool frequency telemetry (sanitized), feature proposals, and Chrysalis realized-value feedback.

---

## Suggested Structure

### Content Structure

All structured intellectual property, source code, synthetic fixtures, and Docs-as-Code documentation reside in this Git repository:

| Path | Purpose |
| --- | --- |
| `packages/etl-migration-core/` | `etl-migration-core` PyPI package: canonical ETL IR & target SPI (`contracts/`), secure discovery (`intake/`), source adapters (`sources/alteryx`, `sources/informatica_powercenter`, `sources/informatica_idmc`), and target registry/placeholders (`targets/`) |
| `packages/etl-portfolio-assessment/` | `etl-portfolio-assessment` PyPI package: target-neutral portfolio assessment (`assessment/`), redacted graph evidence (`evidence/`), and stateless `etl-assess` CLI (`service/`) |
| `packages/etl-target-fabric/` | `etl-target-fabric` PyPI package: Microsoft Fabric fit evaluator & support matrix (`assessment/`), F-SKU capacity model (`capacity/`), M/PySpark/Pipeline compilers (`compilers/`), artifact writer & dry-run planner (`delivery/`), and stateless `etl-fabric` CLI |
| `src/accelerator/` | Local application shell (`fabric-etl-migration-accelerator`): FastAPI loopback routes (`server/`), Typer CLI (`cli/`), SQLite WAL run/snapshot state (`runtime/`), GitHub/GitLab CI dispatchers (`delivery/`), Windows desktop host (`desktop/`), and target registry assembly (`targets/`) |
| `apps/web/` | React 19 + TypeScript + Vite 7-tab analyst workbench (`Portfolio` assessment separated from `Fabric Deployment` code generation/dispatch) and Vitest suites |
| `apps/etl-migration-assessment-app/` | Fabric-native Analyst App (Rayfin static hosting + User Data Functions + semantic model queries) |
| `scripts/` | PowerShell 7 and Node deployment automation (`Deploy-AcceleratorWorkspace.ps1`, `Deploy-FabricArtifacts.ps1`, `Start-LocalApp.ps1`, `Build-Desktop.ps1`, `build-fema-bundle.mjs`) |
| `alteryx-workflows/` | Hermetic, 100% synthetic Alteryx Designer sample workflows (`01_low_*` through `11_multi_container_reconciliation.yxmd`) |
| `tests/` | Pytest unit, adapter, compiler, API, CLI, compatibility, and acceptance suites plus synthetic Informatica fixtures (`tests/fixtures/powercenter/`, `tests/fixtures/idmc/`) |
| `generated-fabric-workflows/` | Deterministically generated Fabric Dataflow Gen2, Notebook, and Data Pipeline envelopes, manifests, and `deployment-plan.json` |
| `docs/` | Architecture (`docs/Architecture/`), user & CI/CD guides (`docs/Guides/`), planning/ADRs (`docs/Planning/`), quality/SDL evidence (`docs/Quality/`), threat model (`docs/Security/`), and release notes (`docs/Release/`) |
| `index.md`, `toc.yml`, `docfx.json` | Chrysalis **Docs-as-Code** (DocFX) Wiki landing page, navigation hierarchy, and site build configuration |
| `chrysalis-manifest.json` | Chrysalis IP Collection manifest template for portal onboarding |

Binary pursuit/delivery collateral (such as executive presentations or engagement workshops), if shared with the community, should be hosted in an approved Microsoft Teams / SharePoint collaboration channel rather than committed as binary blobs in Git, with changes tracked via repository Issues.

### Contribution Process

1. **Feedback & Issue Tracking (Mandatory First Step)**
   - **Consumers & Contributors**: Open a GitHub Issue describing the bug, unsupported ETL tool/transformation, or documentation improvement before submitting a pull request. Informal discussions on Microsoft Teams or Chrysalis comments that lead to repository or documentation changes must be captured as a GitHub Issue so every change has traceable rationale.
2. **Privacy & Sanitization Guardrails (Zero Exceptions)**
   - **Never** attach or commit customer-identifiable `.yxmd`, `.xml`, or `.zip` exports, customer/organization names, engagement acronyms, Microsoft Entra tenant/subscription/workspace GUIDs, local user paths (`C:\Users\...`), or secrets.
   - Construct minimal **synthetic** fixtures under `tests/fixtures/` or `alteryx-workflows/` to reproduce and test new ETL patterns.
3. **Branching & Pull Request Workflow**
   - Create a topic branch from `main` referencing the issue (for example, `feat/issue-42-powercenter-lookup` or `docs/issue-45-ci-guide`).
   - Follow Test-Driven Development: add unit and golden/acceptance tests covering both supported compilation and fail-closed `scaffold` diagnostics for unsupported configurations.
   - Update documentation (`README.md`, `docs/`, and `toc.yml` if adding a new Markdown page) and regenerate `generated-fabric-workflows/` if synthetic sample outputs change.
   - Open a Pull Request against `main`, complete the PR checklist, and request review from `CODEOWNERS`. All CI checks (`python`, `web`, `security-audit`, `codeql`) must pass prior to merge.
   - CI runs on pull request events, including updates to an open pull request. Push events do not trigger CI.

---

## Tools

Contributors use the following standard toolchain to develop, validate, and maintain this repository:

| Tool | Required Version | Role in Workflow | Setup & Reference |
| --- | --- | --- | --- |
| **Python** | `3.13` | Backend runtime, parsers, compilers, FastAPI, Typer CLI | [python.org](https://www.python.org/downloads/) or `uv python install 3.13` |
| **uv** | Latest | Deterministic Python package/lockfile (`uv.lock`) and virtualenv manager | [docs.astral.sh/uv](https://docs.astral.sh/uv/getting-started/installation/) |
| **Ruff / mypy / pytest** | Locked in `uv.lock` | Python linting, `--strict` static type checking, and `>=80%` coverage test runner | Run via `uv run --extra dev <tool>` |
| **pip-audit** | Latest via `uvx` | Python dependency CVE scanning (`uvx pip-audit --strict`) | [pypi.org/project/pip-audit](https://pypi.org/project/pip-audit/) |
| **Node.js & npm** | `22.x` | Building, linting (`eslint`), and testing (`vitest`) the React UI in `apps/web/` | [nodejs.org](https://nodejs.org/) |
| **PowerShell** | `7.0+` (`pwsh`) | Executing and dry-run testing `scripts/Deploy-FabricArtifacts.ps1` | [aka.ms/powershell](https://aka.ms/powershell) |
| **DocFX** | `2.x` (optional locally) | Previewing Chrysalis Docs-as-Code Wiki (`docfx.json` + `toc.yml`) | [dotnet.github.io/docfx](https://dotnet.github.io/docfx/) |
| **Git & GitHub CLI** | Latest | Branch workflow, issue linking, and PR submission (`gh pr create`) | [cli.github.com](https://cli.github.com/) |

For complete local setup commands, see [Installation and Runtime Modes](docs/Guides/installation.md).
