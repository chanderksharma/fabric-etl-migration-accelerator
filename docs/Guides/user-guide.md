---
title: User Guide
description: Complete end-to-end user guide for assessing ETL estates, modeling Fabric capacity, generating Fabric artifacts, and deploying via CI/CD
ms.date: 2026-11-22
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
* Azure Databricks, Azure Synapse Analytics, and Snowflake (roadmap placeholders; installing a provider alone does not integrate generation and deployment into the local portal)

For local path-based intake, an extracted IDMC export is copied into a durable snapshot.
Directory entry and size limits apply, and linked entries are rejected. A changed snapshot
must be reviewed again.

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

1. Open **New assessment** and pick **Alteryx**, **Informatica**, or **Installed plugins**.
2. Choose **Files**, **ZIP / Package**, or **Folder** (use the repository's synthetic `alteryx-workflows` or `tests/fixtures` folders for a safe walkthrough).
3. Review the pre-run discovery summary showing accepted candidates, SHA-256 deduplicated skips, and any rejected paths (UNC paths, symlinks, and ZIP-bomb violations are blocked).
4. Click **Confirm and assess** to start a durable SQLite WAL run. The scheduler
   processes up to four workflows concurrently and supports lease recovery across
   restarts. Cancellation stops additional scheduling when observed; it does not
   interrupt a parser already running.

For **Installed plugins**, install and register the source adapter first. Select its
files, an archive, or a folder separately from built-in sources. The resulting
target-neutral workspace shows source facts and manual-review findings, and can
evaluate registered targets that advertise evaluation support. It does not generate
or deploy artifacts. The synthetic plugin examples demonstrate the integration,
not production SSIS or Databricks support.

The remaining steps apply to the existing Alteryx and Informatica Fabric workspace.

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

   The local API can also queue one target without writing files. This path is
   not in the portal and has no CLI command. `target` must be `notebook`,
   `dataflow`, or `pipeline`. It does not accept `both` or `all`.

   * `POST /api/runs/{run_id}/jobs?target=notebook` returns `202` and a queued job.
   * `GET /api/runs/{run_id}/jobs` lists that run's jobs. Poll until the job is `completed` or `failed`, then read its `error` field if it failed.
   * `GET /api/runs/{run_id}/workflows/{index}/candidates?target=notebook` returns one workflow. The index is zero-based in the confirmed snapshot.

   A completed job includes candidates and does not update
   `generated-fabric-workflows`. `POST /api/runs/{run_id}/generate` remains
   synchronous: it still returns the candidate list and writes artifacts.
   One workflow's unexpected fault becomes a `blocked` candidate so the rest of
   the estate can continue. That fault is not cached. Disk errors, database
   errors, and contract rejections, including an unsupported source, still fail
   the request. See [System Architecture](../Architecture/system-architecture.md#local-generation-runtime).

   Portal previews, dry runs, and ZIP downloads use isolated temporary directories
   and do not update the shared `generated-fabric-workflows` directory. Use the CLI
   `tool generate` command or the legacy generation API when you need persisted local
   artifacts. CI dispatch writes to the shared directory by default. To leave it
   untouched, select **Isolate local deployment planning** or set
   `isolate_local_artifacts` to `true` in the deployment request. This uses
   temporary local files only; the remote CI repository must already contain the
   intended artifacts. It does not establish remote artifact provenance.
   Generation fails if two candidates for
   the same target would receive the same Fabric logical ID; this prevents publishing
   colliding definitions until a compatible identity migration is available. Current
   logical IDs also change when source content changes, so do not assume regenerated
   artifacts will update an existing Fabric item.

   To create and verify a separate run-scoped local publication, use:

   ```powershell
   uv run tool publish <completed-run-id>
   uv run tool verify-publication <completed-run-id> <publication-digest>
   ```

   The publication is stored under the local `.accelerator/publications` directory.
   Its manifest records file hashes; verification rejects modified or extra files.
   Treat it as read-only. To use it for dispatch, copy the exact publication into
   `published-fabric-workflows/<completed-run-id>/<publication-digest>` in the
   remote repository, and select that digest and the full expected commit SHA in
   the deployment form. The publication is not uploaded automatically. Follow
   your data-handling policies when placing artifacts in a repository.
   The local API also supports `POST /api/runs/{run_id}/publications`,
   `GET /api/runs/{run_id}/publications/{digest}`, and
   `GET /api/runs/{run_id}/publications/{digest}/download`. The download contains
   only manifest-listed files and is rejected if the publication has changed.

2. Inspect `generated-fabric-workflows/<platform>/<workflow>/`:
   * Deployable items include `*-create-item.json` envelopes, decoded definitions (`dataflow-mashup.pq`, `notebook-content.ipynb`, `pipeline-content.json`), `.platform` metadata, and `deployment-bundle.json`.
   * Unsupported or macro-dependent items emit `*-diagnostics.json` scaffolds only and are never given runnable create-item envelopes.
3. Run a pre-deployment dry run, then dispatch your allowlisted GitHub Actions or GitLab CI workflow (configured with Microsoft Entra OIDC federation per [Fabric CI/CD Setup](fabric-ci-cd-setup.md)) to publish to your Fabric `dev` workspace.
   You can optionally request a check against a full lowercase commit SHA. This
   check only runs when the selected ref contains the updated trusted CI
   definition and verification script; older GitLab definitions can ignore the
   request. With a publication digest, the local service compares regenerated
   artifacts to the publication and the updated CI definition checks the exact
   manifest and files. These checks depend on a trusted CI definition, checkout,
   and runner; dispatch alone is not proof of remote provenance. See
   [Fabric CI/CD Setup](fabric-ci-cd-setup.md#optional-publication-backed-dispatch).

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

The main CLI also offers `uv run tool assess-neutral <path>` for a target-neutral
assessment using registered source plugins. It returns a nonzero exit code when no
supported workflows are found or parsing fails. The existing `tool assess` command
continues to return the Fabric-specific assessment.

To inspect registered target platforms and roadmap placeholder status from the main CLI or API:

```powershell
uv run tool targets
uv run tool plugins
```

`tool plugins` (and `GET /api/plugins`) also reports every installed plugin as `loaded`,
`failed`, or `skipped` with the reason, so a plugin that does not appear in the portal can
be diagnosed without reading logs. See [Troubleshooting](troubleshooting.md#plugins-faults-and-local-state).

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
| `blocked` | Input validation, a dependency constraint, or an isolated unexpected generation fault prevents a deployable definition. Disk, database, and contract errors fail the request instead. | No (`*-diagnostics.json` only) |

## Security and operational guardrails

* Keep customer workflows, tenant GUIDs, credentials, and personal paths out of source control and issue trackers.
* Bind `tool serve` strictly to `127.0.0.1`; remote exposure is blocked by host and CSRF origin checks.
* Replace all unresolved `source_paths`, connection bindings, and `transform_bindings` placeholders before promoting generated items beyond Development.
* Review [Troubleshooting](troubleshooting.md) if Power BI Direct Lake refreshes lag, notebook schemas need initialization, or workspace deployment encounters permission errors.
