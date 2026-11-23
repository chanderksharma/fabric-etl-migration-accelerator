---
title: Troubleshooting
description: Common issues and resolutions for intake, plugins, generation jobs, and Fabric CI/CD
ms.date: 2026-11-22
ms.topic: troubleshooting
---

Common issues and resolutions across local intake, code generation, and Microsoft Fabric CI/CD deployment.

## Intake and Discovery

| Symptom | Cause | Resolution |
| --- | --- | --- |
| `InputRejectedError` (CLI exit code `2`) | Path points to a symbolic link, UNC share, reparse point, or archive exceeding safety budgets | Copy the archive/folder to a standard local disk path; verify expanded archive size is `< 2 GiB`, entry count `< 10,000`, and compression ratio `< 100:1`. |
| Switching between **Alteryx** and **Informatica** clears selection | Each assessment snapshot is scoped to a single source platform family by design | Run separate assessments for Alteryx estates and Informatica estates. |
| PowerCenter `.xml` file skipped or rejected | XML root is not `<POWERMART>` or exceeds 64 nesting levels / 100,000 elements | Export repository workflows/mappings from Informatica Repository Manager in standard `powrmart.dtd` XML format. |
| Browser upload fails on large estate ZIP | Browser multipart upload cap is `100 MiB` | Use **Local path** mode in the local UI (`http://127.0.0.1:8050`) or run `uv run tool assess <local-path>` to scan up to `2 GiB`. |

## Plugins, Faults, and Local State

| Symptom | Cause | Resolution |
| --- | --- | --- |
| An installed plugin is not loaded | It failed to import, duplicated an existing identity, declared a non-string identity or version attribute or an invalid `supported_extensions` entry (extensions must be lowercase, such as `.dtsx`), declared an incompatible `spi_version`, or is not in `ACCELERATOR_PLUGIN_ALLOWLIST` | Open `GET /api/plugins` (or run `uv run tool plugins`) for the per-plugin `loaded`, `failed`, or `skipped` result and its reason. A broken plugin never blocks the built-in sources and targets. |
| Plugin load result says the SPI version is incompatible | The plugin sets `spi_version` to a value other than `1.0.0` | Remove `spi_version` or set it to `1.0.0`. A missing value means `1.0.0`. `2.0.0` is rejected. |
| A file is skipped with `Source adapter '<id>' faulted during probe` | The plugin raised an unexpected exception while recognizing the file | Fix the plugin; adapters should return `None` for unrecognized input and raise `ValueError` for invalid input. The file is skipped and the rest of the input is still discovered. |
| A workflow fails with `faulted during parse` or `unexpected <ExceptionType>` | A plugin or engine raised an unexpected exception for that one workflow | The workflow is listed under failures and the run still completes. Set `ACCELERATOR_LOG_LEVEL=DEBUG` and check the standard error log for the traceback. |
| Run ends `failed` with `abandoned after 5 interrupted attempts` | The process stopped five times while running it, so a workflow may be crashing the parser | Remove the suspect workflow from the selection and start a new run. |
| `.accelerator` keeps growing | Caches, snapshots, and publications are retained until you prune them | Run `uv run tool gc --dry-run`, then `uv run tool gc`, with the portal stopped. |
| `Unsupported run database schema version` | The state directory was written by a newer release | Use the newer release, or point `ACCELERATOR_STATE_DIR` at a new directory. |

## Code Generation and Readiness

| Symptom | Cause | Resolution |
| --- | --- | --- |
| Workflow produces `*-diagnostics.json` instead of `*-create-item.json` | Workflow contains unsupported macros, custom plugins, or multi-mapping orchestration (`scaffold` state) | Inspect `dataflow-diagnostics.json` / `notebook-diagnostics.json`; scaffolds are design evidence only and intentionally omitted from deployment envelopes. |
| A candidate diagnostic starts with `unexpected generation fault` | One workflow raised an unexpected exception during generation | That workflow is `blocked` and is not cached. The rest of the estate can still generate. Read the server log for the traceback, then fix the producer. Disk, database, and contract errors do not take this path. |
| Generation job status is `failed` | The assessment is not complete, the target is unsupported, the writer hit a disk or database error, or the job was interrupted five times | Complete the assessment before `POST /api/runs/{id}/jobs`. Read the job `error` field. A job abandoned after five interrupted attempts must be submitted again. A completed job does not write `generated-fabric-workflows`. |
| `POST /api/runs/{id}/generate` returns 409 | The writer hit a disk error, a database error, or a contract rejection such as an unsupported source | Read the response detail. Queueing a generation job does not hide these errors, and a successful job does not write files. |
| Fabric target, wave, effort, or capacity changed after opening **Fabric Deployment** | Expected. Portfolio assessment is static, and opening that tab confirms each route with the compilers. `routing_basis` changes from `static_mapping` to `compiler_confirmed`. | Nothing to fix. Complexity, tool counts, and findings do not change. Exports taken earlier carry `X-Routing-Basis: static_mapping`. |
| Fabric Deployment shows an error and **Routing basis** stays on static mapping | The fit stage failed, for example on a disk or database error. The stored assessment is unaffected. | Read the message, fix the cause, and open the tab again to retry. Set `ACCELERATOR_LOG_LEVEL=DEBUG` and check the standard error log. |
| A confirmed run reads as static mapping again after an upgrade | The stored fit was computed with other compiler, rules, or support-table versions, so it is ignored instead of reinterpreted | Open **Fabric Deployment** again, or call `POST /api/runs/{id}/targets/fabric/evaluate`, to confirm with the installed versions. |
| A run from an earlier release says `compiler_confirmed` and has no stored fit | Its results were already compiler-routed when it ran, so it is served as stored | Nothing to fix. Start a new run to use the separate assessment and fit stages. |
| Deployment reports `BindingsRequired` | Generated Dataflow or Notebook requires workspace-specific source connections or Lakehouse/Warehouse destination IDs | Bind source connections and target destinations in the Fabric `dev` workspace before enabling Dataflow refresh or Notebook execution. |
| `SPNBasedRefreshNotAllowed` during Fabric deployment | Microsoft Fabric blocks service-principal-initiated Dataflow Gen2 refresh jobs | Expected platform limitation: `Deploy-FabricArtifacts.ps1` validates saved queries via `executeQuery` (`SPNQueryValidated`); trigger full refresh under an authorized user or supported orchestration identity. |

## CI/CD and Runner Operations

| Symptom | Cause | Resolution |
| --- | --- | --- |
| Workspace deployment reports `EnvironmentLibrariesNotFound` immediately after creating or reusing the Fabric Environment | Fabric has not created a staged-library collection yet | Use the current `Deploy-AcceleratorWorkspace.ps1` and rerun the same command. The installer treats this exact response as an empty collection, uploads the wheels and external libraries, and continues. Other Environment API errors remain fatal. |
| Rayfin reports that the previously deployed Fabric item is gone, followed by `An item with the name ... of type AppBackend already exists` | The AppBackend was soft-deleted and is still in the workspace recycle bin, so its name remains reserved | Use the current `Deploy-AcceleratorWorkspace.ps1` and rerun the same command. When the Rayfin registry's workspace ID, item name, and item ID match the recoverable AppBackend, the installer restores it and its child items before deployment. If it was permanently deleted, pass a new `-FabricAppName`. |
| GitHub Actions run fails immediately with *hosted runners are disabled* | Microsoft EMU disables default GitHub-hosted runners unless org runner groups are assigned | Register a self-hosted Windows X64 runner (`[self-hosted, Windows, X64]`) with PowerShell 7, or set repository/org variable `CI_RUNNER_LABELS` (CI and package jobs) and `DEPLOY_RUNNER_LABELS` (deployment, pipeline-provisioning, and ALM promotion workflows) to your organization runner group JSON array. |
| `Missing environment variables: AZURE_CLIENT_ID, AZURE_TENANT_ID` | `dev` environment variables/secrets not configured | Configure Entra OIDC federation (`id-token: write` + federated credential on the Entra app) with `AZURE_CLIENT_ID` and `AZURE_TENANT_ID` in the `dev` environment (or supply `AZURE_CLIENT_SECRET` fallback). |
| `409 Conflict` when viewing workflow evidence | Local source file was modified after snapshot confirmation | Create a new preview snapshot and run a fresh assessment. |
