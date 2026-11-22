---
title: Getting Started
description: Run an end-to-end ETL assessment and generate Microsoft Fabric artifacts
ms.date: 2026-11-22
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

From the repository root, build and launch the app directly from the four workspace `.whl` packages:

```powershell
pwsh -NoProfile -File scripts\Start-LocalApp.ps1
```

Or run in editable developer mode:

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
   - Export estate assessment summaries as **JSON** or formula-defused **CSV**, or click **Open Fabric Deployment** to proceed to code generation.
   - Open **Workflows** and click any workflow row to open the **six-tab workflow inspection drawer** (Summary, Canvas Graph, Source Register, Generated Code, Readiness & Diagnostics, and Fabric Deployment handoff).
   - Switch to **Technical Details** for filterable, paginated tool and endpoint registers, and **Capacity Sizing** to model Fabric F-SKU capacity.

## 3. Generate and Export Microsoft Fabric Artifacts

Open the **Fabric Deployment** tab in the sidebar (or click **Continue to Fabric Deployment** from a workflow drawer):

- Select the target platform (**Microsoft Fabric** is ready; **Databricks**, **Azure Synapse**, and **Snowflake** appear as fail-closed roadmap placeholders).
- Generate **Dataflow Gen2** (`mashup.pq` + `queryMetadata.json`), **Fabric Notebook** (`.ipynb`), and **Data Pipeline** (`pipeline-content.json`) previews, or download target/workflow ZIP packages.
- Select ready workflows, run dry-run validation, and dispatch GitHub Actions or GitLab CI workflows.

Equivalent CLI workflow:

```powershell
uv run tool preview .\alteryx-workflows
uv run tool assess .\alteryx-workflows
uv run tool generate <completed-run-id> --target all --output generated-fabric-workflows
```

The API can queue one target and return cached candidates without writing
`generated-fabric-workflows`. That path is not a portal button. Use the CLI
`generate` command when you need a local artifact tree. See the
[User Guide](user-guide.md#step-4-generate-artifacts-and-dispatch-cicd).

### Validate Generated Notebooks

Validate generated PySpark notebooks in a Fabric workspace configured for
Fabric Runtime 2.0 before production use. Runtime 2.0 uses Apache Spark 4.1,
Python 3.13, and Delta Lake 4.2.

The local Python 3.13 environment runs the accelerator itself. It does not
replace validation in the Fabric-managed runtime.

## Next Steps

- Review [Installation & Runtime Modes](installation.md) for one-step FEMA Fabric workspace deployment as well as local, CLI, Windows desktop, and Docker loopback options.
- Follow [Fabric CI/CD Setup](fabric-ci-cd-setup.md) to configure secretless Microsoft Entra OIDC deployment via GitHub Actions or GitLab CI.
- Read [`CONTRIBUTING.md`](../../CONTRIBUTING.md) before adding new Alteryx tools or Informatica transformations.
