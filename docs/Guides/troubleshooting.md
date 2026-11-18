# Troubleshooting

Common issues and resolutions across local intake, code generation, and Microsoft Fabric CI/CD deployment.

## Intake and Discovery

| Symptom | Cause | Resolution |
| --- | --- | --- |
| `InputRejectedError` (CLI exit code `2`) | Path points to a symbolic link, UNC share, reparse point, or archive exceeding safety budgets | Copy the archive/folder to a standard local disk path; verify expanded archive size is `< 2 GiB`, entry count `< 10,000`, and compression ratio `< 100:1`. |
| Switching between **Alteryx** and **Informatica** clears selection | Each assessment snapshot is scoped to a single source platform family by design | Run separate assessments for Alteryx estates and Informatica estates. |
| PowerCenter `.xml` file skipped or rejected | XML root is not `<POWERMART>` or exceeds 64 nesting levels / 100,000 elements | Export repository workflows/mappings from Informatica Repository Manager in standard `powrmart.dtd` XML format. |
| Browser upload fails on large estate ZIP | Browser multipart upload cap is `100 MiB` | Use **Local path** mode in the local UI (`http://127.0.0.1:8050`) or run `uv run tool assess <local-path>` to scan up to `2 GiB`. |

## Code Generation and Readiness

| Symptom | Cause | Resolution |
| --- | --- | --- |
| Workflow produces `*-diagnostics.json` instead of `*-create-item.json` | Workflow contains unsupported macros, custom plugins, or multi-mapping orchestration (`scaffold` state) | Inspect `dataflow-diagnostics.json` / `notebook-diagnostics.json`; scaffolds are design evidence only and intentionally omitted from deployment envelopes. |
| Deployment reports `BindingsRequired` | Generated Dataflow or Notebook requires workspace-specific source connections or Lakehouse/Warehouse destination IDs | Bind source connections and target destinations in the Fabric `dev` workspace before enabling Dataflow refresh or Notebook execution. |
| `SPNBasedRefreshNotAllowed` during Fabric deployment | Microsoft Fabric blocks service-principal-initiated Dataflow Gen2 refresh jobs | Expected platform limitation: `Deploy-FabricArtifacts.ps1` validates saved queries via `executeQuery` (`SPNQueryValidated`); trigger full refresh under an authorized user or supported orchestration identity. |

## CI/CD and Runner Operations

| Symptom | Cause | Resolution |
| --- | --- | --- |
| GitHub Actions run fails immediately with *hosted runners are disabled* | Microsoft EMU disables default GitHub-hosted runners unless org runner groups are assigned | Register a self-hosted Windows X64 runner (`[self-hosted, Windows, X64]`) with PowerShell 7, or set repository/org variable `CI_RUNNER_LABELS` to your organization runner group JSON array. |
| `Missing environment variables: AZURE_CLIENT_ID, AZURE_TENANT_ID` | `dev` environment variables/secrets not configured | Configure Entra OIDC federation (`id-token: write` + federated credential on the Entra app) with `AZURE_CLIENT_ID` and `AZURE_TENANT_ID` in the `dev` environment (or supply `AZURE_CLIENT_SECRET` fallback). |
| `409 Conflict` when viewing workflow evidence | Local source file was modified after snapshot confirmation | Create a new preview snapshot and run a fresh assessment. |
