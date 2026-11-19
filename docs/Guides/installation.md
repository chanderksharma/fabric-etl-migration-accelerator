---
title: Installation and Runtime Modes
description: Install and run the accelerator locally, from the CLI, in a dev container, or in Docker
ms.date: 2026-11-17
ms.topic: how-to
---

## Installation and Runtime Modes

The **Microsoft Fabric ETL Migration Accelerator** runs locally on an engineer's workstation as a loopback-bound Python + React service, a standalone CLI, or a local Docker container.

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
