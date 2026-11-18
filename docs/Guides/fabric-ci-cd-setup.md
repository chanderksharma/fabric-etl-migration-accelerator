---
title: Fabric CI/CD Setup
description: Configure deterministic Development deployment and governed Fabric ALM promotion
---

## Overview

Use this guide to configure Microsoft Fabric artifact deployment through
GitHub Actions or GitLab CI.

Both providers call
[`scripts/Deploy-FabricArtifacts.ps1`](../../scripts/Deploy-FabricArtifacts.ps1).
The script deploys generated Dataflow Gen2, Fabric Notebook, and Data Pipeline
definition envelopes from `generated-fabric-workflows`.

GitHub Actions can also use
[`scripts/Invoke-FabricAlm.ps1`](../../scripts/Invoke-FabricAlm.ps1) to commit
the authoritative Development workspace to Git and manually promote adjacent
Fabric Deployment Pipeline stages.

## Deployment model

| Capability | GitHub Actions | GitLab CI |
| --- | --- | --- |
| Configuration file | `.github/workflows/deploy-fabric-artifacts.yml` | `.gitlab-ci.yml` |
| Manual trigger | Workflow dispatch | New pipeline |
| API trigger | GitHub workflow dispatch API | GitLab Pipelines API |
| Runner | Self-hosted Windows X64 | Runner tagged `fabric-deploy-windows` |
| Shell | PowerShell 7 | PowerShell 7 |
| Environment | `dev` | `dev` |
| Serialization | Workspace concurrency group | Workspace resource group |
| Dry run | Supported | Supported |
| Fabric workspace to Git | Optional, repository-variable gated | Not configured |
| Test and Production promotion | Manual GitHub workflow | Not configured |

> [!IMPORTANT]
> A successful definition deployment does not approve semantic parity, bind
> external data sources, or refresh a Dataflow. Complete source, destination,
> schema, row-count, and business-rule validation before promotion.

## Shared prerequisites

Prepare these resources before configuring either provider:

1. A Microsoft Entra service principal.
2. A Fabric workspace on active capacity.
3. Fabric tenant settings that allow the service principal to call Fabric
   APIs.
4. Contributor or higher access for the service principal on the target
   workspace.
5. Generated definitions under `generated-fabric-workflows`.
6. A runner with PowerShell 7 and network access to Microsoft Entra and Fabric.

Record these values outside source control:

| Variable | Value |
| --- | --- |
| `AZURE_CLIENT_ID` | Service-principal application/client ID |
| `AZURE_TENANT_ID` | Microsoft Entra tenant ID |
| `AZURE_CLIENT_SECRET` | Optional fallback client secret (omit when using Entra OIDC federation) |
| `FABRIC_WORKSPACE_ID` | Target Fabric workspace GUID |

Never commit service-principal credentials.

## Fabric-authoritative ALM foundation

The ALM foundation keeps deterministic REST deployment as the bootstrap path
into Development. After validation, the Fabric Development workspace becomes
the source of truth:

```text
Generated definitions
        |
        v
REST deployment to Development
        |
        v
Fabric Development workspace
        |
        +--> commitToGit --> connected Git branch
        |
        +--> Deployment Pipeline --> Test --> Production
```

Git synchronization is disabled by default. Existing Development deployment
continues unchanged until `FABRIC_SYNC_DEVELOPMENT_TO_GIT` is set to `true`.

The synchronization step fails closed when Fabric reports remote-only changes
or conflicts. It never overwrites a remote change. Keep the connected
Development branch under a single-writer model: Fabric commits to the branch,
and external automation must not push competing item-definition changes to the
same branch.

### Prepare Fabric Git integration

Before enabling Development-to-Git synchronization:

1. Connect the Development workspace to the intended GitHub repository,
   branch, and directory.
2. Configure the service principal's Git credentials in Fabric.
3. Use a PAT-backed Fabric configured connection for GitHub. Entra OIDC
   authenticates the workflow to Fabric, but it does not replace the GitHub
   credential stored by the Fabric Git connection.
4. Grant the service principal Contributor or higher access to Development and
   `Workspace.GitCommit.All`.
5. Confirm the workspace is assigned to Fabric capacity.

The synchronization commits every pending workspace change by using
`commitToGit` mode `All`. Reserve the Development workspace and branch for the
controlled accelerator flow, or review pending workspace changes before
enabling the repository variable.

### Prepare the Fabric Deployment Pipeline

Create a Fabric Deployment Pipeline with adjacent stages such as Development,
Test, and Production. Assign one workspace to each stage.

The deployment identity requires:

- Admin access to the Fabric Deployment Pipeline
- Contributor or higher access to both source and target workspaces
- The `Pipeline.Deploy` delegated scope
- Service-principal support for every item included in the promotion

Add these GitHub repository variables:

| Variable | Required | Default or purpose |
| --- | --- | --- |
| `FABRIC_SYNC_DEVELOPMENT_TO_GIT` | Yes for Git sync | Set to `true` after Git integration is ready |
| `FABRIC_DEPLOYMENT_PIPELINE_ID` | Yes for promotion | Fabric Deployment Pipeline GUID |
| `FABRIC_DEV_STAGE_NAME` | No | `Development` |
| `FABRIC_TEST_STAGE_NAME` | No | `Test` |
| `FABRIC_PROD_STAGE_NAME` | No | `Production` |
| `FABRIC_VARIABLE_LIBRARY_NAME` | No | Variable Library display name |
| `FABRIC_DEV_VALUE_SET_NAME` | No | Development value set name |
| `FABRIC_TEST_VALUE_SET_NAME` | No | `test` |
| `FABRIC_PROD_VALUE_SET_NAME` | No | `prod` |
| `FABRIC_DEPLOYMENT_PLAN_ID` | No | Preview Deployment Plan item GUID |

### Configure manual approvals

Create `test` and `prod` GitHub environments. Configure required reviewers,
deployment branch restrictions, and environment-specific Entra OIDC
credentials. The
[`promote-fabric-alm.yml`](../../.github/workflows/promote-fabric-alm.yml)
workflow selects the environment from the requested target stage:

- Test promotion uses Development as its source and the `test` environment
- Production promotion uses Test as its source and the `prod` environment

The workflow only supports manual `workflow_dispatch`. It does not run on push
or pull request events.

### Choose promotion items

The promotion workflow defaults to `promotion_scope: Selected`. Supply
`selected_items` as a JSON array of exact, case-sensitive source item names and
Fabric item types:

```json
[
  {"name": "03_low_unique_customers", "type": "Dataflow"},
  {"name": "Notebook_1", "type": "Notebook"}
]
```

Select `dependencies_reviewed` only after reviewing Fabric lineage and checking
that dependencies are included in the selection or already exist in the target.
The stage-items API does not expose a dependency graph. The workflow does not
claim automatic dependency discovery or add related items implicitly. Staging
Lakehouse and Warehouse items are included only when explicitly selected or when
you choose `All`.

Choose `promotion_scope: All` and leave `selected_items` empty or `[]` for a
whole-stage promotion. Both modes require between 1 and 300 resolved items.
Empty Selected requests, malformed JSON, duplicate requests, and unknown or
ambiguous name/type matches fail without falling back to All.

The workflow runs in two jobs:

1. A read-only planning job uses the source GitHub environment: `dev` for Test
   promotions, or `test` for Production promotions. It resolves source-stage IDs
   and publishes a summary of the exact item IDs, types, and create/update actions.
2. The promotion job depends on that plan and uses the target GitHub environment.
   Review the planning summary before approving Production. The job rechecks the
   plan against current stage assignments, selections, pairings, and options.
   Changed plans fail and require a new planning run.

Both jobs need the Azure authentication secrets in their respective environments.
The native deploy request always contains the explicit, non-empty item list,
including in All mode. Selected item pairings are verified after deployment,
and existing unselected target item metadata is checked for unexpected changes.
The plan fixes the item scope, not the underlying item definitions; keep the
source workspace stable during release approval. No data refresh is performed.

For a read-only plan from PowerShell, followed by an explicitly reviewed promotion:

```powershell
$Parameters = @{
    DeploymentPipelineId = $env:FABRIC_DEPLOYMENT_PIPELINE_ID
    SourceStageName = 'Test'
    TargetStageName = 'Production'
    PromotionScope = 'Selected'
    SelectedItemsJson = '[{"name":"Notebook_1","type":"Notebook"}]'
    DependenciesReviewed = $true
}
$Plan = & .\scripts\Invoke-FabricAlm.ps1 -Operation PlanPromotion @Parameters |
    Out-String
$Plan | ConvertFrom-Json | Format-List
# Review the plan before executing this separate command.
& .\scripts\Invoke-FabricAlm.ps1 -Operation Promote @Parameters -ReviewedPlanJson $Plan
```

`Promote -DryRun` remains an offline configuration check. It does not resolve
items or replace the read-only `PlanPromotion` operation.

### Configure Variable Library stages

Create Development, Test, and Production value sets in one Fabric Variable
Library definition. The library is promoted with the other supported Fabric
items, but the active value set is workspace item state and is not stored in
Git.

After each promotion, `Invoke-FabricAlm.ps1`:

1. Finds the Variable Library by display name in the target workspace.
2. Sets `properties.activeValueSetName`.
3. Reads the Variable Library state back and verifies the selected value set.

Leave `FABRIC_VARIABLE_LIBRARY_NAME` unset when no Variable Library is used.
The workflow passes an active value set only when a library is configured.
Activation is performed only when that Variable Library is included in the
resolved promotion scope; an unselected library is left unchanged.

> [!WARNING]
> Deployment Plan support in the Fabric deployment API is Beta. The promotion
> workflow requires both `FABRIC_DEPLOYMENT_PLAN_ID` and the explicit
> `use_preview_deployment_plan` input before it sends the Beta request.

## Deployment inputs

Both providers expose equivalent deployment controls.

| Input | Default | Accepted values |
| --- | --- | --- |
| Workspace ID | Development workspace | Fabric workspace GUID |
| Deployment ID | `manual` | Correlation text |
| Artifact root | `generated-fabric-workflows` | Repository-relative directory |
| Target | `Both` | `Both`, `Bundle`, `Dataflow`, `Notebook`, `DataPipeline` |
| Workflow filter | `*` | Workflow-directory wildcard |
| Conflict behavior | `Update` | `Fail`, `Skip`, `Update` |
| Dry run | `false` | `true`, `false` |

Use `Dry run = true` for the first execution. Dry runs validate and list
definition envelopes without authenticating to Fabric or changing Fabric
items.

## GitHub Actions setup

The workflow is
[`deploy-fabric-artifacts.yml`](../../.github/workflows/deploy-fabric-artifacts.yml).

### Configure the runner

Register an online self-hosted runner with these labels:

- `self-hosted`
- `Windows`
- `X64`

Install PowerShell 7 on the runner.

### Configure the environment

In the GitHub repository:

1. Open **Settings > Environments**.
2. Create or select the `dev` environment.
3. Add these environment secrets:
   - `AZURE_CLIENT_ID`
   - `AZURE_TENANT_ID`
   - `AZURE_CLIENT_SECRET` *(optional — only required if OIDC federation is not configured)*
4. Add required reviewers or deployment branch restrictions where applicable.

For Microsoft Entra Workload Identity Federation (OIDC), configure a federated
credential with subject `repo:<owner>/<repository>:environment:dev` and audience
`api://AzureADTokenExchange`, and omit `AZURE_CLIENT_SECRET`.

When `AZURE_CLIENT_SECRET` is configured, the shared authentication helper uses
it instead of automatically requesting a GitHub OIDC token. Explicit
`AZURE_FEDERATED_TOKEN` or `AZURE_FEDERATED_TOKEN_FILE` settings retain priority.

The workspace ID is supplied as a workflow input. It is not a secret.

### Run manually

1. Open **Actions > Deploy Fabric artifacts**.
2. Select **Run workflow**.
3. Choose the branch containing the generated artifacts.
4. Set **Dry run** to `true`.
5. Select the target and workflow filter.
6. Run the workflow and inspect the deployment summary.
7. Change **Dry run** to `false` only after review.

When Development is connected to Git and ready to become authoritative, set
`FABRIC_SYNC_DEVELOPMENT_TO_GIT=true`. A successful non-dry-run deployment then
commits pending Development workspace changes to its connected branch.

### Promote manually

1. Open **Actions > Promote Fabric ALM**.
2. Select **Run workflow**.
3. Choose `Test` or `Production`.
4. Choose `Selected`, enter the name/type JSON, and confirm dependency review.
   Choose `All` explicitly only when a whole-stage release is intended.
5. Enter an audit note.
6. Leave preview Deployment Plan support disabled unless it has been evaluated.
7. Submit the workflow and review the completed planning job's summary before
   approving the target environment.
8. Verify the selected item pairings and any selected target Variable Library
   active value set.

### Configure accelerator dispatch

For production or team use, configure a GitHub App on the accelerator server:

| Environment variable | Purpose |
| --- | --- |
| `GITHUB_AUTH_MODE=github-app` | Select GitHub App authentication |
| `GITHUB_APP_ID` | GitHub App ID |
| `GITHUB_APP_PRIVATE_KEY_PATH` | Absolute path to the App private key |
| `GITHUB_ALLOWED_REPOSITORIES` | Comma-separated repository allowlist |

Grant the GitHub App Actions read/write permission. Metadata read permission is
automatic.

For local development only, `GITHUB_AUTH_MODE=gh-cli` uses the active GitHub
CLI login.

## GitLab CI setup

GitLab remains a Development-only deployment path in this foundation. Native
Fabric Git synchronization and Test/Production promotion are implemented in
the GitHub workflows.

The pipeline is [`.gitlab-ci.yml`](../../.gitlab-ci.yml).

### Configure the runner

Register a GitLab Runner that:

- Runs Windows.
- Uses PowerShell 7.
- Has the tag `fabric-deploy-windows`.
- Can reach Microsoft Entra and Fabric endpoints.
- Is authorized for the project or inherited from its group.

The job does not run on untagged runners.

### Configure CI/CD variables

In the GitLab project:

1. Open **Settings > CI/CD**.
2. Expand **Variables**.
3. Add:

| Key | Recommended protection | Environment scope |
| --- | --- | --- |
| `AZURE_CLIENT_ID` | Masked; Protected when `main` is protected | `dev` |
| `AZURE_TENANT_ID` | Masked; Protected when `main` is protected | `dev` |
| `AZURE_CLIENT_SECRET` | Masked, Hidden, Protected | `dev` |
| `FABRIC_WORKSPACE_ID` | Protected when `main` is protected | `dev` |

If variables are protected, protect the `main` branch so the deployment job
can receive them.

### Run manually

1. Open **Build > Pipelines**.
2. Select **New pipeline**.
3. Select `main`.
4. Set `DRY_RUN` to `true`.
5. Choose `TARGET`, `WORKFLOW_FILTER`, and `CONFLICT_BEHAVIOR`.
6. Run the pipeline.
7. Review the dry-run output.
8. Use `DRY_RUN=false` only after the service-principal variables and artifacts
   are verified.

The pipeline accepts manually created Web pipelines and API-created pipelines.
Push pipelines are ignored.

### Configure accelerator dispatch

Configure these values on the accelerator server:

| Environment variable | Purpose |
| --- | --- |
| `GITLAB_BASE_URL` | GitLab origin, such as `https://gitlab.com` |
| `GITLAB_TOKEN` | Server-side token with `api` scope |
| `GITLAB_ALLOWED_PROJECTS` | Comma-separated project allowlist |

Prefer a project access token when the GitLab tier supports it. Group or
personal access tokens can use the same API scope when organizational policy
permits them. Never expose the token to the browser.

The backend verifies `.gitlab-ci.yml` on the selected ref and calls:

```text
POST /projects/:id/pipeline
```

It sends the same deployment controls listed in this guide as pipeline
variables.

> [!NOTE]
> GitLab.com can require account identity verification before CI jobs run.
> This is a GitLab anti-abuse control rather than a pipeline-file error.

## Local dry-run validation

Run one workflow locally before enabling live CI deployment:

```powershell
pwsh -NoLogo -NoProfile `
  -File .\scripts\Deploy-FabricArtifacts.ps1 `
  -WorkspaceId "<fabric-workspace-guid>" `
  -ArtifactRoot generated-fabric-workflows `
  -Target Dataflow `
  -WorkflowFilter "alteryx-workflows/11_multi_container_reconciliation" `
  -ConflictBehavior Update `
  -DryRun
```

Expected output includes:

- `Action: WouldDeploy`
- Required definition part names
- `BindingsRequired` when source or destination bindings are unresolved

## Live deployment behavior

With dry run disabled, the script:

1. Validates generated create-item envelopes.
2. Acquires a Fabric token with the service principal.
3. Creates, skips, fails, or updates matching Fabric items.
4. Deploys bundles in Dataflow, Notebook, then Data Pipeline order.
5. Reads definitions back and verifies required parts.
6. Runs saved-query validation only for runtime-ready Dataflows.

Service-principal Dataflow refresh can return
`SPNBasedRefreshNotAllowed`. The deployment script does not claim refresh
success in that case. Definitions with unresolved bindings report
`BindingsRequired`.

## Security checklist

- Keep all tokens and secrets in provider secret stores.
- Protect the `main` branch and `dev` environment.
- Restrict GitHub App repositories and GitLab projects with allowlists.
- Use a dedicated deployment runner.
- Review changes to CI files and the deployment script.
- Start with dry run.
- Do not treat successful deployment as semantic parity approval.
- Rotate service-principal secrets and repository tokens regularly.

## Troubleshooting

| Symptom | Resolution |
| --- | --- |
| No matching envelopes | Check `ARTIFACT_ROOT`, `TARGET`, and `WORKFLOW_FILTER`. |
| `BindingsRequired` | Configure Dataflow source and destination connections. |
| Missing Azure variables | Add the service-principal variables to the provider environment. |
| Job remains pending | Confirm an online runner has the required labels or tag. |
| GitLab identity verification required | Complete GitLab.com verification or contact GitLab Support. |
| Existing item stops deployment | Use `Update` or `Skip`, or remove the conflicting item. |
| Pipeline dependency error | Deploy Dataflow and Notebook before Data Pipeline. |

