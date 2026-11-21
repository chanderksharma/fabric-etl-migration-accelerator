---
title: User Guide
description: Complete end-to-end user guide for assessing ETL estates, modeling Fabric capacity, generating Fabric artifacts, and deploying via CI/CD
ms.date: 2026-11-21
ms.topic: how-to
---

## Overview

The **Microsoft Fabric ETL Migration Accelerator (FEMA)** provides deterministic discovery, target-neutral portfolio assessment, Microsoft Fabric code generation, F-SKU capacity sizing, and secretless CI/CD deployment for legacy ETL estates.

Supported source formats:

* Alteryx Designer workflows, macros, analytic apps, and packages (`.yxmd`, `.yxmc`, `.yxwz`, `.yxzp`)
* Informatica PowerCenter repository XML exports (`powrmart.dtd` standalone or zipped)
* Informatica Intelligent Data Management Cloud (IDMC) export ZIP archives and extracted manifest directories (`.DTEMPLATE`, `.MTT`, `.TASKFLOW`)

Registered destination targets:

* Microsoft Fabric (implemented: target-fit evaluation, F-SKU capacity sizing, Dataflow Gen2, PySpark Notebook, Data Pipeline, and dry-run planning)
* Azure Databricks, Azure Synapse Analytics, and Snowflake (registered as fail-closed roadmap placeholders until dedicated provider wheels are installed)

> [!IMPORTANT]
> The accelerator never executes imported source workflows, scripts, or SQL statements. Every generated artifact carries `generated_unvalidated` status until required source/destination bindings are wired and independent semantic parity is verified.

## Choose your runtime mode

| Mode | Best suited for | Required runtime | Entry point |
| :--- | :--- | :--- | :--- |
| Fabric-native FEMA workspace | Portfolio leadership BI, shared workspace intake, Spark Delta persistence | Microsoft Fabric workspace (Runtime 2.0) | Fabric Analyst App (`fema-etl-migration-app`) and Power BI Report |
| Local Analyst Web UI and Desktop | Full interactive assessment, graph inspection, code preview, and GitOps dispatch | Python 3.13 + Node 22 build | `uv run tool serve` or `uv run --extra desktop tool desktop` |
| Modular Python CLIs (`etl-assess`, `etl-fabric`) | Headless CI pipelines, single-asset inspection, future IDE integrations | Python 3.13 + core/target wheels | `etl-assess` and `etl-fabric` |
| Offline browser utility | Air-gapped portfolio triage without Python or server setup | Modern Edge or Chrome | `apps/portable/alteryx-portfolio.html` |

See [Installation and Runtime Modes](installation.md) for deployment commands and container instructions.

## Workflow 1: Fabric-native FEMA workspace

Deploy the FEMA stack into a Microsoft Fabric workspace using [Deploy-AcceleratorWorkspace.ps1](../../scripts/Deploy-AcceleratorWorkspace.ps1) or the in-Fabric [Deploy_FEMA.ipynb](../../notebooks/Deploy_FEMA.ipynb) notebook. All items are organized inside the `FEMA` workspace folder.

### Stage and assess workflows in Fabric

1. Open the deployed Fabric Analyst App (`fema-etl-migration-app`) from your Fabric workspace.
2. Upload `.yxmd`, `.yxmc`, `.yxwz`, `.yxzp`, PowerCenter `.xml`, or IDMC `.zip` exports (up to 3 MiB per file in browser intake; larger estates can be staged directly in Lakehouse `Files/`).
3. Start the assessment job. The app triggers `ETL Migration Assessment` (`notebooks/fabric-portfolio-assessment.ipynb`) on Spark Runtime 2.0 using the lightweight `etl-migration-core`, `etl-portfolio-assessment`, and `etl-target-fabric` wheels.
4. When the notebook finishes, it persists eight `etl_*` Delta tables in `ETL_Migration_Assessment_Lakehouse`, sets `IsLatestCompletedRun = true` on the new run, and triggers a Direct Lake framing refresh on `ETL Migration Assessment Model`.

### Review the 5-page Power BI leadership report

Open `ETL Migration Assessment` (Power BI Report) to inspect portfolio outcomes across five pages:

1. **Executive Summary**: Displays latest-run KPIs, platform distribution, complexity bands, and recommended Fabric targets. Use the **Assessment Run** slicer to switch across historical runs.
2. **Wave Plan**: Organizes assets into **Wave 1** through **Wave 4**, showing wave counts, complexity, and tool mix for migration sequencing.
3. **Blockers & Risks**: Surfaces unsupported tools, manual redesign candidates, macro/package dependencies, and parser findings.
4. **Fabric Capacity**: Estimates CU-seconds per run, monthly CU-hours, and balanced F-SKU recommendations across the assessed portfolio.
5. **Run History**: Tracks assessment runs over time (`RunId`, timestamp, workflow counts, and failure counts).

## Workflow 2: Local Analyst Web UI and Windows Desktop

Build and start the loopback service directly from the built `.whl` packages (`scripts\Start-LocalApp.ps1`), or run in editable developer mode:

```powershell
pwsh -NoProfile -File scripts\Start-LocalApp.ps1
```

Open `<http://127.0.0.1:8050>` in your browser, or pass `-Desktop` (`pwsh -NoProfile -File scripts\Start-LocalApp.ps1 -Desktop`) for the native Windows WebView2 window.

### Step 1: Preview and confirm intake

1. Open **New assessment** and pick the source family (**Alteryx** or **Informatica**).
2. Choose **Files**, **ZIP / Package**, or **Folder** (use the repository's synthetic `alteryx-workflows` or `tests/fixtures` folders for a safe walkthrough).
3. Review the pre-run discovery summary showing accepted candidates, SHA-256 deduplicated skips, and any rejected paths (UNC paths, symlinks, and ZIP-bomb violations are blocked).
4. Click **Confirm and assess** to start a durable SQLite WAL run. Long-running batches support cancellation and lease recovery across restarts.

### Step 2: Inspect the portfolio and 6-tab workflow drawer

1. Open **Portfolio** to filter assessed workflows by platform, complexity band, target component, or migration wave (**Wave 1** through **Wave 4**), export assessment JSON/CSV reports, or click **Open Fabric Deployment** when ready to generate target code.
2. Open **Workflows** and select any workflow row to open its six-tab inspection drawer:
   * Summary tab showing complexity score, migration wave, residual effort estimate, and recommendation rationale
   * Canvas Graph tab showing the visual DAG reconstructed from redacted node and edge evidence
   * Source Register tab listing the tool or operation inventory, data endpoints, and dependencies
   * Generated Code tab previewing compiled Power Query M (`mashup.pq`), PySpark notebook cells, or Data Pipeline JSON, or explicit scaffold diagnostics when compilation is blocked
   * Readiness & Diagnostics tab highlighting missing runtime bindings (`source_paths`, `transform_bindings`, `destination`), unsupported tools, and the semantic parity checklist
   * Fabric Deployment tab showing readiness metadata, workflow bundle download, and a **Continue to Fabric Deployment** handoff button that opens the dedicated deployment tab with that workflow preselected
3. Use **Technical Details** to search across full tool, endpoint, and dependency registers and export formula-safe CSV files.

### Step 3: Model Fabric capacity

Open **Capacity Sizing** (see [Fabric Capacity Planning](capacity-planning.md)) to adjust operational assumptions such as refresh interval, source rows per run, Spark vCores, target utilization, and Spark billing mode (`capacity` vs `autoscale`). The calculator produces **Optimized**, **Balance**, and **Peak** F-SKU recommendations (`F2` through `F8192`) and exports a formula-defused capacity CSV.

### Step 4: Generate artifacts and dispatch CI/CD

1. Open the **Fabric Deployment** tab in the sidebar, verify **Microsoft Fabric** is selected in **Target Platform** (roadmap placeholders for Azure Databricks, Azure Synapse Analytics, and Snowflake are shown as disabled), and generate Fabric definitions (`Dataflow Gen2`, `Fabric Notebook`, `Data Pipeline`), inspect filterable code/scaffold previews, or download target/workflow ZIP packages. You can also generate definitions via CLI:

   ```powershell
   uv run tool generate <completed-run-id> --target all --output generated-fabric-workflows
   ```

2. Inspect `generated-fabric-workflows/<platform>/<workflow>/`:
   * Deployable items include `*-create-item.json` envelopes, decoded definitions (`dataflow-mashup.pq`, `notebook-content.ipynb`, `pipeline-content.json`), `.platform` metadata, and `deployment-bundle.json`.
   * Unsupported or macro-dependent items emit `*-diagnostics.json` scaffolds only and are never given runnable create-item envelopes.
3. Run a pre-deployment dry run, then dispatch your allowlisted GitHub Actions or GitLab CI workflow (configured with Microsoft Entra OIDC federation per [Fabric CI/CD Setup](fabric-ci-cd-setup.md)) to publish to your Fabric `dev` workspace.

## Workflow 3: Modular Python packages and stateless CLIs

Use the standalone libraries when embedding assessment or Fabric compilation into CI pipelines, notebooks, or custom automation without FastAPI or SQLite:

* `etl-migration-core`: Canonical `EtlPackage` IR, discovery, source adapters, and `TargetPlatformRegistry`
* `etl-portfolio-assessment`: Target-neutral portfolio assessment and `etl-assess` CLI
* `etl-target-fabric`: Microsoft Fabric evaluator, F-SKU capacity model, M/PySpark/Pipeline compilers, and `etl-fabric` CLI

```powershell
etl-assess preview .\alteryx-workflows
etl-assess assess .\alteryx-workflows
etl-assess evidence .\alteryx-workflows

etl-fabric evaluate .\alteryx-workflows\sample_alteryx_workflow.yxmd
etl-fabric compile .\alteryx-workflows\sample_alteryx_workflow.yxmd --target dataflow
```

To inspect registered target platforms and roadmap placeholder status from the main CLI or API:

```powershell
uv run tool targets
```

See [Building Source and Target Plugins](building-plugins.md) to register custom source adapters or implement providers for Databricks, Azure Synapse, or Snowflake, and [PyPI Packages and Publishing Guide](pypi-packages.md) for installation, build, and release instructions.

## Understanding waves, targets, and diagnostics

### Migration wave normalization (Wave 1 to Wave 4)

| Engine wave | Normalized UI and BI label | Typical profile |
| :--- | :--- | :--- |
| `Wave 1` | `Wave 1` | Low complexity, single native target (Dataflow Gen2 or Notebook) |
| `Pilot` | `Wave 2` | High complexity or mixed multi-item Fabric solution requiring early pilot validation |
| `Wave 2` | `Wave 3` | Medium complexity standard migration workload |
| `Redesign` | `Wave 4` | Unsupported tools, macros, or cyclic/control tasks requiring manual redesign |

### Validation states

| State | Meaning | Deployable envelope emitted |
| :--- | :--- | :--- |
| `generated_unvalidated` | Compiler produced structurally valid Fabric definition; bindings and semantic parity still require review | Yes (`*-create-item.json`) |
| `scaffold` | One or more operations, macros, or graph shapes fall outside verified compiler coverage | No (`*-diagnostics.json` only) |
| `blocked` | Input validation or dependency constraint prevents safe generation | No (`*-diagnostics.json` only) |

## Security and operational guardrails

* Keep customer workflows, tenant GUIDs, credentials, and personal paths out of source control and issue trackers.
* Bind `tool serve` strictly to `127.0.0.1`; remote exposure is blocked by host and CSRF origin checks.
* Replace all unresolved `source_paths`, connection bindings, and `transform_bindings` placeholders before promoting generated items beyond Development.
* Review [Troubleshooting](troubleshooting.md) if Power BI Direct Lake refreshes lag, notebook schemas need initialization, or workspace deployment encounters permission errors.
