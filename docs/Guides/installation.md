---
title: Installation and Runtime Modes
description: Install and run the accelerator locally, from the CLI, in a dev container, or in Docker
ms.date: 2026-11-17
ms.topic: how-to
---

## Installation and Runtime Modes

The **Microsoft Fabric ETL Migration Accelerator** runs as a loopback-bound
Python + React service, a standalone CLI, or a local Docker container. For
portfolio assessment only, use the standalone offline HTML utility.

## Offline ETL portfolio assessment

1. Download [alteryx-portfolio.html](../../apps/portable/alteryx-portfolio.html)
   and open the saved file in a current, organization-approved Edge or Chrome
   browser with local JavaScript enabled. No installation, local server, or
   Fabric sign-in is required.
2. In **New Assessment**, choose **Alteryx** or **Informatica** for format
   guidance, then choose **Select file(s)** or **Select folder**. Select
   Alteryx `.yxmd`, `.yxmc`, or `.yxwz` files or PowerCenter repository
   `.xml` exports. Folder selection includes supported files in subfolders.
   For IDMC, select the
   extracted export root containing `manifest.json` directly. The folder
   must retain the asset subfolders and their `metadata.json` and graph
   `asset.json` files. Choose **Assess portfolio** to assess the selected inputs.
   Extract ZIP and `.yxzp` packages with an approved archive tool first.
   The utility accepts up to 1,000 input files and 1,000 assessed assets, with
   limits of 10 MiB per file read and 100 MiB per batch. Duplicate standalone
   files are counted once.
3. Review assessment scope and wave totals in **Portfolio**. Open
   **Workflows** to compare complexity, suggested targets, and manual tool
   types, or to filter the register by source or migration wave. **Export full portfolio
   CSV** downloads every assessed row for Excel, even when the table is filtered.
4. Open a workflow to review its **Summary**, **Source Workflow**, **Fabric
   Design**, **Risk Assessment**, and **Validation** tabs. The Source Workflow
   diagram shows active components and connections. The Fabric Design diagram adds
   suggested mappings and flags tools for manual review. These are static
   diagrams; the browser never executes a workflow.
5. In **Migration Plan**, select a wave card to filter the backlog and
   review the next steps. In **Technical Details**,
   choose an evidence register, then filter by workflow or search its
   contents. **Export current register** downloads all matching records.
6. Use **Readiness** in **Workflows** to find assets that need a manual
   mapping, dependency, expression, or design review. A pilot candidate
   still needs validation. Offline target routing distinguishes compute from
   orchestration and checks selected operation constraints. The original
   inventory-based target and baseline wave remain available for comparison.
7. To compare with the Python app, export `assessment.json` from a completed
   Python assessment and import it under **Portfolio → Compare with Python
   assessment** after assessing the same inputs offline. The HTML checks
   source fingerprints, asset identity, registry and rules versions, and
   graph metrics before using a matched Python target in recommendations,
   filters, and exports. The Python wave is shown for comparison only.
   Use the same extracted directory in both apps for IDMC; a report based
   on the ZIP has a different fingerprint. Unmatched assets keep their
   offline recommendations. **Export comparison CSV** preserves the original
   inventory target, offline routed target, and imported target when available.
   Effort estimates and delivery durations are not shown or exported
   by the offline utility.

The utility reads selected files in the browser without uploading them or
saving assessment state. Treat the JSON and CSV reports as internal portfolio
data: they can contain workflow file names and tool types. The utility counts
file references and expression elements without including their raw values.
Source evidence shows up to 200 tools and 200 connections per workflow;
assessment totals use the full parsed graph. PowerCenter coverage includes
workflows, linked session mappings, and standalone mappings. IDMC coverage
includes mappings (`DTEMPLATE`), mapping tasks (`MTT`), and taskflows
(`TASKFLOW`) in the supported manifest-based JSON format. Offline routing is
an assessment heuristic, not compiler or runtime validation.
Macro dependency resolution, artifact generation, live Fabric checks, and
deployment are not supported in this mode.

## Assessment in a Fabric notebook

Use the [portfolio assessment notebook](../../notebooks/fabric-portfolio-assessment.ipynb)
to run the Python assessment engine without a separate app. The notebook
uses the same compiler-backed target routing as the analyst web app.

1. Build the accelerator wheel on an approved build machine with
   `uv build --wheel`. Add it and its approved dependencies to a Fabric
   Environment using [Runtime 2.0](https://learn.microsoft.com/fabric/data-engineering/runtime-2-0).
   Publish the environment. The notebook requires the PySpark runtime with
   Python 3.13 or later, not the standalone Python notebook kernel.
2. Import the `.ipynb` into Fabric, attach the published environment, and
   attach an approved default Lakehouse. Stage approved exports under
   Lakehouse **Files**. Select a file, an archive, or a directory by setting
   `INPUT_PATH` relative to **Files**. For an extracted IDMC package, point
   it to the directory containing `manifest.json` and `Explore`.
3. Run **Preview the input** and review candidates and skips. Set
   `CONFIRM_ASSESSMENT = True` in the configuration cell and rerun it before
   running **Assess and review portfolio**. Use `SOURCE_FILTER`,
   `WORKFLOW_SEARCH`, and `DETAIL_PATH` to inspect results. Rerun the
   configuration and workflow register cells after changing those filters.
   The workflow register cell renders a responsive portfolio dashboard with
   summary cards, complexity, target, wave and source distributions, and a
   ranked high-complexity workflow table before the full Fabric data grid.
   Run **Migration plan** for wave cards, target distributions, next actions
   and exit evidence. Run **Technical details** for redacted evidence metrics,
   tool mappings, findings, dependencies and a bounded connection sample.
   Run the workflow cells after Technical details. Each web-UI subtab has a
   separate cell: **Workflow summary**, **Source workflow**, **Fabric design**,
   **Risk assessment**, **Validation**, and **Tool mappings**. Set
   `DETAIL_PATH` to an exact register path and rerun these cells to inspect a
   different workflow.
4. To save reports, set `WRITE_REPORTS = True`, rerun the configuration cell,
   and run **Export reports**. Reports go to a new run folder under
   `REPORT_FOLDER`. Keep the report folder outside the selected input.
   The offline utility can import `assessment.json` when the file
   fingerprints and assessment versions match.

The notebook processes files inside Fabric, not on your workstation.
Reports contain workflow names and fingerprints. The notebook does not
export effort estimates, save generated Fabric definitions, or deploy items.

## Power BI assessment report

The [Power BI project](../../powerbi/ETL%20Migration%20Assessment.pbip) provides
a six-page analyst report over normalized Lakehouse tables. It uses Direct
Lake, retains assessment history, filters operational pages to the latest
completed run, and includes an **Assessment Run History** page across retained
runs.

1. Set `PERSIST_DELTA_TABLES = True` in the notebook configuration. Run the
   assessment and **Persist normalized assessment tables** cells to populate
   the eight `etl_*` Delta tables (`etl_assessment_run`, `etl_workflow_assessment`,
   `etl_tool_inventory`, `etl_finding`, `etl_dependency`, `etl_workflow_node`,
   `etl_workflow_connection`, and `etl_capacity_profile`).
2. Run `node scripts/generate-powerbi-report.mjs` to regenerate the approved
   PBIR page definitions. Validate them with
   `powerbi-report-author validate "powerbi\ETL Migration Assessment.Report"`.
3. Build a deployment payload without storing tenant-scoped identifiers in
   source control:

   ```powershell
   node scripts\build-powerbi-semantic-model-payload.mjs `
     --workspace-id <workspace-guid> `
     --lakehouse-id <lakehouse-guid> `
     --out semantic-model-create.json
   ```

4. Deploy the generated payload to a development workspace through the Fabric
   semantic model API. Bind or publish the PBIR report only after the Direct
   Lake model and all report pages pass live rendering validation.

## Fabric analyst app

The [Fabric analyst app](../../apps/etl-migration-assessment-app/) provides an
authenticated custom experience for intake, notebook execution, run status,
portfolio analytics, workflow review, migration planning, and technical
evidence. It uses Fabric Apps static hosting, a delegated semantic model
connector, and server-side Functions.

The analyst views include a leadership decision brief and readiness scorecard,
searchable workflow register, workflow-level source, design, risk, validation,
and deployment tabs (with one-click deployment preselection), migration wave
gates and rationale, technical evidence registers, and an interactive
capacity-planning page using persisted static workflow profiles (`model v3.1.0`)
with fallback heuristics when older runs lack profile rows. Calibrate capacity
estimates against measured pilot evidence before making a capacity or cost
commitment.

Before deploying, confirm that the Fabric Apps workload, Semantic Model Execute
Queries API, and external OneLake access tenant settings are enabled. The app
owner also needs access to the target Lakehouse and notebook.

1. Configure the source-controlled connector placeholders through environment
   variables:

   ```powershell
   Set-Location apps\etl-migration-assessment-app
   $env:FABRIC_WORKSPACE_ID = '<workspace-guid>'
   $env:FABRIC_SEMANTIC_MODEL_ID = '<semantic-model-guid>'
   $env:VITE_REPORT_URL = '<published-report-url>'
   ```

2. Sign in, validate, and deploy:

   ```powershell
   npx rayfin login
   npm run lint
   npm test
   npm run build:fabric
   npm --prefix rayfin\functions run build
   npx rayfin up --workspace <workspace-name> --dry-run
   npx rayfin up --workspace <workspace-name>
   ```

3. Configure the deployed Function settings with `npx rayfin secret set` for
   `FABRIC_WORKSPACE_ID`, `FABRIC_LAKEHOUSE_ID`, and `FABRIC_NOTEBOOK_ID`.
   Enter each value at the masked prompt. Do not store these values in source
   control.

4. Configure the signed deployment preview:

   ```powershell
   npx rayfin secret set DEPLOYMENT_CONFIRMATION_KEY
   ```

   Use a randomly generated secret with at least 32 bytes of entropy. The app
   signs each preview for ten minutes and requires an explicit confirmation
   before dispatch.

5. To enable GitHub Actions deployment, configure a token and a comma-separated
   repository allow-list:

   ```powershell
   npx rayfin secret set GITHUB_TOKEN
   npx rayfin secret set GITHUB_ALLOWED_REPOSITORIES
   ```

   Enter allow-list values as `owner/repository`. The token needs permission to
   read repository metadata and dispatch
   `.github/workflows/deploy-fabric-artifacts.yml`.

6. To enable GitLab CI deployment, configure a token and a comma-separated
   project allow-list:

   ```powershell
   npx rayfin secret set GITLAB_TOKEN
   npx rayfin secret set GITLAB_ALLOWED_PROJECTS
   ```

   Enter allow-list values as `group/project`. For a self-managed GitLab
   instance, also run `npx rayfin secret set GITLAB_BASE_URL` and enter its
   HTTPS origin.

> [!IMPORTANT]
> Fabric deployment is dispatch-only. The app validates the provider, allow-list,
> CI definition, ref, generated artifact paths, and selected targets. It then
> displays a signed manifest for review. Only the confirmed manifest can dispatch
> one existing CI workflow or pipeline per selected ready workflow. Provider
> tokens remain in Fabric App secrets and are never returned to the browser.

The intake flow accepts `.yxmd`, `.yxmc`, `.yxwz`, `.yxzp`, `.xml`, `.json`,
and `.zip` files up to 3 MiB each. Files are staged under
`Files/app-intake/<run-folder>` before the app starts the assessment notebook
with persistence enabled.

## Option 1: Local Workstation Setup (Recommended)

### Install dependencies

```powershell
uv python install 3.13
uv sync --extra dev --locked

Set-Location apps\web
npm ci
npm run build
Set-Location ..\..
```

### Start the integrated UI and API server

```powershell
uv run tool serve --port 8050
```

The FastAPI server binds strictly to `127.0.0.1:8050` and serves the compiled React UI from `apps/web/dist`.

Assessment navigation, the active run reference, filters, selected files, and
deployment form values are browser-session state. A new browser session starts
at Intake without restoring them. Reloading the same tab can restore its active
run. Theme preference remains persistent. This cleanup does not delete SQLite
runs, immutable snapshots, or generated Fabric artifacts.

### UI hot-reload development mode

When iterating on the React frontend (`apps/web/src`):

```powershell
# Terminal 1: FastAPI backend on 127.0.0.1:8050
uv run tool serve --port 8050

# Terminal 2: Vite dev server
Set-Location apps\web
npm run dev
```

## Option 2: CLI-Only Execution

No Node.js build step is required if you only need headless estate discovery, JSON assessment reports, or deterministic Fabric definition generation:

```powershell
uv sync --locked --no-dev
uv run tool preview C:\path\to\estate
uv run tool assess C:\path\to\estate
```

## Option 3: Windows Desktop Utility

The desktop utility keeps the existing deterministic FastAPI and React
application but hosts it in a native Microsoft Edge WebView2 window. It binds
an authenticated API to a random loopback port and does not expose a fixed
network listener.

### Run from source

Build the UI and restore the optional desktop runtime:

```powershell
Set-Location apps\web
npm ci
npm run build
Set-Location ..\..
uv sync --extra desktop --locked
uv run --extra desktop tool desktop
```

Use `uv run --extra desktop tool desktop --debug` to open WebView developer
tools while troubleshooting.

### Build the portable desktop package

```powershell
.\scripts\Build-Desktop.ps1
```

The build produces:

```text
dist\desktop\FabricETLMigrationAccelerator\FabricETLMigrationAccelerator.exe
dist\desktop\FabricETLMigrationAccelerator-windows-x64.zip
```

Extract the entire ZIP before running the executable. Do not copy only the EXE;
the adjacent `_internal` directory contains the Python runtime, WebView host,
and React assets. Microsoft Edge WebView2 Runtime must be installed. It is
included with supported Windows 10 and Windows 11 installations and can be
installed separately by enterprise administrators.

Desktop state is isolated per Windows user:

```text
%LOCALAPPDATA%\Fabric ETL Migration Accelerator\
  state\runs.db
  artifacts\
  logs\desktop.log
  webview\
```

Only one desktop instance runs per Windows user. Closing the window shuts down
its random-port API. The launcher verifies the authenticated API, HTML, and
compiled JavaScript and CSS before showing the window.

The package does not contain `.env`, GitHub App private keys, Entra client
secrets, or customer data. Assessment works without deployment credentials. To
use GitHub dispatch from the desktop, prefer the authenticated GitHub CLI:

```powershell
gh auth login
[Environment]::SetEnvironmentVariable('GITHUB_AUTH_MODE', 'gh-cli', 'User')
[Environment]::SetEnvironmentVariable(
  'GITHUB_ALLOWED_REPOSITORIES',
  'owner/repository',
  'User'
)
```

Set `FABRIC_WORKSPACE_ID` or `ACCELERATOR_DEV_WORKSPACE` as a Windows user
environment variable when dispatching Development deployment. Fabric execution
credentials remain in protected GitHub environments.

### Desktop security boundary

The initial native window URL contains a random per-launch token that is
immediately exchanged for an HTTP-only session cookie and removed by redirect.
Every embedded API request requires that cookie or the private launch header.
PyWebView private mode prevents browser state from becoming a cross-launch
authentication mechanism. This remains a single-user desktop boundary; it is
not a multi-user hosted service.

## Option 4: Local Loopback Container

Build and run the multi-stage container image (`node:22-alpine` UI build + `python:3.13-slim` runtime), publishing **only** to the host loopback interface (`127.0.0.1`):

```powershell
docker build -t fabric-etl-accelerator:1.0.0 .
docker run --rm -p 127.0.0.1:8050:8050 -v fabric-etl-state:/data fabric-etl-accelerator:1.0.0
```

> **Security Note:** Never publish port `8050` on `0.0.0.0` across an untrusted network. The analyst service is designed as a single-user local workstation boundary.

## Option 5: Development Container

Open the repository in a development container to use the supported
Microsoft Python 3.13 image based on Debian Bookworm. The container installs
Node.js 22, PowerShell 7, GitHub CLI, and the locked Python dependencies during
creation.

The development container is for local authoring and validation. Generated
Fabric notebooks must be validated separately against Fabric Runtime 2.0.

## Environment Variables

Copy [`.env.sample`](../../.env.sample) to `.env` only when testing local CI dispatch or dry-run workspace policy checks. `.env` and `.accelerator/` are excluded from Git and Docker build contexts.
