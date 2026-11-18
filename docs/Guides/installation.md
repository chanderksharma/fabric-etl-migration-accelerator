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

## Option 3: Local Loopback Container

Build and run the multi-stage container image (`node:22-alpine` UI build + `python:3.13-slim` runtime), publishing **only** to the host loopback interface (`127.0.0.1`):

```powershell
docker build -t fabric-etl-accelerator:1.0.0 .
docker run --rm -p 127.0.0.1:8050:8050 -v fabric-etl-state:/data fabric-etl-accelerator:1.0.0
```

> **Security Note:** Never publish port `8050` on `0.0.0.0` across an untrusted network. The analyst service is designed as a single-user local workstation boundary.

## Option 4: Development Container

Open the repository in a development container to use the supported
Microsoft Python 3.13 image based on Debian Bookworm. The container installs
Node.js 22, PowerShell 7, GitHub CLI, and the locked Python dependencies during
creation.

The development container is for local authoring and validation. Generated
Fabric notebooks must be validated separately against Fabric Runtime 2.0.

## Environment Variables

Copy [`.env.sample`](../../.env.sample) to `.env` only when testing local CI dispatch or dry-run workspace policy checks. `.env` and `.accelerator/` are excluded from Git and Docker build contexts.
