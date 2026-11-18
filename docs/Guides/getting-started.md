---
title: Getting Started
description: Run an end-to-end ETL assessment and generate Microsoft Fabric artifacts
ms.date: 2026-11-17
ms.topic: tutorial
---

## Getting Started

This guide walks delivery engineers, migration architects, and contributors through running their first end-to-end ETL assessment and Microsoft Fabric code generation pass.

## Prerequisites

| Tool | Version | Purpose |
| --- | --- | --- |
| **Python** | `3.13` | Core assessment, compiler, API, and CLI runtime |
| **uv** | Latest | Locked Python dependency and virtual-environment manager |
| **Node.js & npm** | `22.x` | Building and testing the React analyst UI (`apps/web`) |
| **PowerShell** | `7.0+` (`pwsh`) | Running `scripts/Deploy-FabricArtifacts.ps1` |
| **Fabric Runtime** | `2.0` (GA) | Production validation for generated PySpark notebooks |

## 1. Build and Launch the Analyst Web Application

From the repository root:

```powershell
uv sync --extra dev --locked
Set-Location apps\web
npm ci
npm run build
Set-Location ..\..
uv run tool serve
```

Open **`http://127.0.0.1:8050`** in your browser.

## 2. Run Your First Synthetic Estate Assessment

1. Select **New assessment** in the top navigation bar.
2. Choose **Alteryx** (or **Informatica** for PowerCenter `.xml` / IDMC `.zip` exports).
3. Select **Folder** and choose the repository's synthetic `alteryx-workflows` directory (or `tests/fixtures/powercenter` for Informatica).
4. Review the pre-run discovery summary (discovered workflow count, byte totals, and any skipped files), then click **Confirm and assess**.
5. Inspect the **Portfolio** dashboard:
   - Click any workflow row to open the **six-tab workflow inspection drawer** (Summary, Canvas Graph, Source Register, Generated Code, Readiness & Diagnostics, and Fabric Deployment).
   - Switch to **Technical Details** for filterable, paginated tool and endpoint registers.

## 3. Generate and Export Microsoft Fabric Artifacts

From the **Portfolio** view (or via CLI):

- Export estate assessment summaries as **JSON** or formula-defused **CSV**.
- Generate **Dataflow Gen2** (`mashup.pq` + `queryMetadata.json`), **Fabric Notebook** (`.ipynb`), and **Data Pipeline** (`pipeline-content.json`) packages, or download a workflow-level deployment bundle ZIP.

Equivalent CLI workflow:

```powershell
uv run tool preview .\alteryx-workflows
uv run tool assess .\alteryx-workflows
uv run tool generate <completed-run-id> --target all --output generated-fabric-workflows
```

### Validate Generated Notebooks

Validate generated PySpark notebooks in a Fabric workspace configured for
Fabric Runtime 2.0 before production use. Runtime 2.0 uses Apache Spark 4.1,
Python 3.13, and Delta Lake 4.2.

The local Python 3.13 environment runs the accelerator itself. It does not
replace validation in the Fabric-managed runtime.

## Next Steps

- Review [Installation & Container Setup](installation.md) for local, CLI, and Docker loopback deployment options.
- Follow [Fabric CI/CD Setup](fabric-ci-cd-setup.md) to configure secretless Microsoft Entra OIDC deployment via GitHub Actions or GitLab CI.
- Read [`CONTRIBUTING.md`](../../CONTRIBUTING.md) before adding new Alteryx tools or Informatica transformations.
