# Microsoft Fabric ETL Migration Accelerator — Copilot Instructions

## Project Overview

Deterministic assessment, canonical ETL graph normalization, compiler-grounded Microsoft Fabric code generation (Dataflow Gen2, Fabric Notebook, Data Pipeline), and dispatch-only CI/CD deployment for migrating Alteryx Designer, Informatica PowerCenter, and Informatica IDMC estates.

## Repository Layout

- `packages/etl-migration-core/` — Target-neutral canonical ETL IR (`contracts/ir.py`), Target SPI (`contracts/spi.py`), plugin conformance checks (`contracts/testing.py`), secure archive/file/directory discovery (`intake/{archive,discovery,domain,schemas}.py`), and built-in source adapters (`sources/alteryx`, `sources/informatica_powercenter`, `sources/informatica_idmc`).
- `packages/etl-portfolio-assessment/` — Target-neutral portfolio scoring (`assessment/engine.py`), workload profiling, redacted graph evidence (`evidence/extractor.py`), and stateless `etl-assess` CLI.
- `packages/etl-target-fabric/` — Microsoft Fabric provider (`provider.py`), static assessment (`assessment/`), compiler-grounded fit (`evaluation/native_route.py`), F-SKU capacity model (`capacity/model.py`), compilers (`compilers/{alteryx,ir,expr_ast,m_literals}.py`), artifact writer & notebook encoder (`delivery/`), and stateless `etl-fabric` CLI.
- `src/accelerator/` — Python 3.13 FastAPI server (`server/{api,deployment,schemas,uploads}.py`), Typer CLI (`cli/app.py`), SQLite WAL run orchestration (`runtime/{runs,store,snapshots,capacity,publications,targets,identity,models,publication,artifacts}.py`), CI dispatchers (`delivery/{base,github,gitlab,provenance}.py`), settings/logging (`settings.py`), and Windows Desktop shell (`desktop/`).
- `examples/plugins/` — Independently packaged synthetic example plugins (`synthetic-ssis`, `synthetic-databricks`) validating entry-point discovery.
- `apps/web/` — React 19 + TypeScript + Vite analyst portfolio UI.
- `scripts/` — PowerShell 7 deployment/ALM/verification scripts (`Deploy-FabricArtifacts.ps1`, `FabricApi.psm1`, `Invoke-FabricAlm.ps1`, `Assert-DeploymentPublication.ps1`, etc.) and Node payload builders.
- `alteryx-workflows/` & `tests/fixtures/` — Hermetic synthetic test corpus (zero customer data).
- `generated-fabric-workflows/` — Deterministically generated Fabric request envelopes and manifests.
- `docs/` — Architecture, user/deployment guides, threat model, and release notes (published via DocFX `docfx.json` + `toc.yml` + `index.md`).

## Engineering & Chrysalis Guardrails

1. **Zero Customer or Personal Data**: Never commit customer workflows, customer names, tenant/subscription/workspace GUIDs, local user paths, or credentials.
2. **Deterministic Non-AI Core**: Never execute untrusted workflow expressions or introduce non-deterministic LLM calls into the parser/compiler pipeline. Unsupported source constructs must emit explicit `scaffold` diagnostics and never receive runnable-looking `*-create-item.json` envelopes.
3. **Validation Gate**: Run `uv run --extra dev ruff check src packages tests examples`, `uv run --extra dev mypy`, `uv run --extra dev pytest --cov-fail-under=80`, and `npm run lint && npm test && npm run build` in `apps/web` before committing.
