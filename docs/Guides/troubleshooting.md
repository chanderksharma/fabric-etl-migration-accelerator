# Troubleshooting

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
| An installed plugin is missing from the portal | It failed to import, duplicated an existing identity, declared a non-string identity or version attribute or an invalid `supported_extensions` entry (extensions must be lowercase, such as `.dtsx`), or is not in `ACCELERATOR_PLUGIN_ALLOWLIST` | Open `GET /api/plugins` (or run `uv run tool plugins`) for the per-plugin `loaded`, `failed`, or `skipped` result and its reason. A broken plugin never blocks the built-in sources and targets. |
| A file is skipped with `Source adapter '<id>' faulted during probe` | The plugin raised an unexpected exception while recognizing the file | Fix the plugin; adapters should return `None` for unrecognized input and raise `ValueError` for invalid input. The file is skipped and the rest of the input is still discovered. |
| A workflow fails with `faulted during parse` or `unexpected <ExceptionType>` | A plugin or engine raised an unexpected exception for that one workflow | The workflow is listed under failures and the run still completes. Set `ACCELERATOR_LOG_LEVEL=DEBUG` and check the standard error log for the traceback. |
| Run ends `failed` with `abandoned after 5 interrupted attempts` | The process stopped five times while running it, so a workflow may be crashing the parser | Remove the suspect workflow from the selection and start a new run. |
| `.accelerator` keeps growing | Caches, snapshots, and publications are retained until you prune them | Run `uv run tool gc --dry-run`, then `uv run tool gc`, with the portal stopped. |
| `Unsupported run database schema version` | The state directory was written by a newer release | Use the newer release, or point `ACCELERATOR_STATE_DIR` at a new directory. |

## Code Generation and Readiness

| Symptom | Cause | Resolution |
| --- | --- | --- |
| Workflow produces `*-diagnostics.json` instead of `*-create-item.json` | Workflow contains unsupported macros, custom plugins, or multi-mapping orchestration (`scaffold` state) | Inspect `dataflow-diagnostics.json` / `notebook-diagnostics.json`; scaffolds are design evidence only and intentionally omitted from deployment envelopes. |
| Deployment reports `BindingsRequired` | Generated Dataflow or Notebook requires workspace-specific source connections or Lakehouse/Warehouse destination IDs | Bind source connections and target destinations in the Fabric `dev` workspace before enabling Dataflow refresh or Notebook execution. |
| `SPNBasedRefreshNotAllowed` during Fabric deployment | Microsoft Fabric blocks service-principal-initiated Dataflow Gen2 refresh jobs | Expected platform limitation: `Deploy-FabricArtifacts.ps1` validates saved queries via `executeQuery` (`SPNQueryValidated`); trigger full refresh under an authorized user or supported orchestration identity. |

## CI/CD and Runner Operations

| Symptom | Cause | Resolution |
| --- | --- | --- |
| GitHub Actions run fails immediately with *hosted runners are disabled* | Microsoft EMU disables default GitHub-hosted runners unless org runner groups are assigned | Register a self-hosted Windows X64 runner (`[self-hosted, Windows, X64]`) with PowerShell 7, or set repository/org variable `CI_RUNNER_LABELS` (CI and package jobs) and `DEPLOY_RUNNER_LABELS` (deployment, pipeline-provisioning, and ALM promotion workflows) to your organization runner group JSON array. |
| `Missing environment variables: AZURE_CLIENT_ID, AZURE_TENANT_ID` | `dev` environment variables/secrets not configured | Configure Entra OIDC federation (`id-token: write` + federated credential on the Entra app) with `AZURE_CLIENT_ID` and `AZURE_TENANT_ID` in the `dev` environment (or supply `AZURE_CLIENT_SECRET` fallback). |
| `409 Conflict` when viewing workflow evidence | Local source file was modified after snapshot confirmation | Create a new preview snapshot and run a fresh assessment. |
