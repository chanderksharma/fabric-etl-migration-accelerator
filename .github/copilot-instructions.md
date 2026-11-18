# Microsoft Fabric ETL Migration Accelerator — Copilot Instructions

## Project Overview

Deterministic assessment, canonical ETL graph normalization, compiler-grounded Microsoft Fabric code generation (Dataflow Gen2, Fabric Notebook, Data Pipeline), and dispatch-only CI/CD deployment for migrating Alteryx Designer, Informatica PowerCenter, and Informatica IDMC estates.

## Repository Layout

- `src/accelerator/` — Python 3.13 FastAPI + Typer CLI + SQLite run service, canonical ETL IR (`etl_ir.py`), source adapters (`sources/alteryx`, `sources/informatica_powercenter`, `sources/informatica_idmc`), compilers (`generation.py`, `etl_generation.py`), and CI dispatchers (`github_deployment.py`, `gitlab_deployment.py`).
- `apps/web/` — React 19 + TypeScript + Vite analyst portfolio UI.
- `scripts/Deploy-FabricArtifacts.ps1` — PowerShell 7 deployment script with Microsoft Entra OIDC federation and readback/saved-query verification.
- `alteryx-workflows/` & `tests/fixtures/` — Hermetic synthetic test corpus (zero customer data).
- `generated-fabric-workflows/` — Deterministically generated Fabric request envelopes and manifests.
- `docs/` — Architecture, user/deployment guides, threat model, and release notes (published to Chrysalis Wiki via DocFX `docfx.json` + `toc.yml` + `index.md`).

## Engineering & Chrysalis Guardrails

1. **Zero Customer or Personal Data**: Never commit customer workflows, customer names, tenant/subscription/workspace GUIDs, local user paths, or credentials.
2. **Deterministic Non-AI Core**: Never execute untrusted workflow expressions or introduce non-deterministic LLM calls into the parser/compiler pipeline. Unsupported source constructs must emit explicit `scaffold` diagnostics and never receive runnable-looking `*-create-item.json` envelopes.
3. **Validation Gate**: Run `uv run --extra dev ruff check src tests`, `uv run --extra dev mypy`, `uv run --extra dev pytest --cov-fail-under=80`, and `npm run lint && npm test && npm run build` in `apps/web` before committing.
