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

Both providers use
[`scripts/Invoke-FabricAlm.ps1`](../../scripts/Invoke-FabricAlm.ps1) for
reviewed adjacent-stage promotion. GitHub Actions also uses it to commit the
authoritative Development workspace to Git.

## Deployment model

| Capability | GitHub Actions | GitLab CI |
| --- | --- | --- |
| Configuration file | `.github/workflows/*.yml` | `.gitlab-ci.yml` + `.gitlab/ci/*.yml` |
| Manual trigger | Workflow dispatch | New pipeline |
| API trigger | GitHub workflow dispatch API | GitLab Pipelines API |
| Runner | Self-hosted Windows X64 | Runner tagged `fabric-deploy-windows` |
| Shell | PowerShell 7 | PowerShell 7 |
| Environment | `dev`, `test`, `prod` | `dev`, `test`, `prod` |
| Serialization | Workspace concurrency group | Workspace resource group |
| Dry run | Supported | Supported |
| Create/reuse Deployment Pipeline | Manual GitHub workflow | `FABRIC_OPERATION=CreatePipeline` |
| Fabric workspace to Git | Optional, repository-variable gated | Not configured |
| Test and Production promotion | Manual GitHub workflow | Planned job + manual protected deployment job |

> [!IMPORTANT]
> A successful definition deployment does not approve semantic parity, bind
> external data sources, or refresh a Dataflow. Complete source, destination,
> schema, row-count, and business-rule validation before promotion.

### Optional deployment revision check

The portal and deployment APIs accept an optional `expected_commit`: a full,
lowercase 40-character commit SHA. The updated GitHub workflow receives it as
`expected_commit`; the updated GitLab job receives `FABRIC_EXPECTED_COMMIT`. Before
deployment, the trusted CI definition compares that value with the CI event
commit and the checked-out Git commit. A mismatch fails the job.

The selected branch or tag must contain the updated CI definition and
`scripts/Assert-DeploymentRevision.ps1`. Protect the CI definition and verify
its presence at the selected ref before relying on this check. Older GitLab
jobs can ignore the variable and deploy without checking it. A moving ref can
also select a different CI definition; the check is not a trusted attestation.
The revision check alone does not compare local and remote artifacts.

### Optional publication-backed dispatch

1. Publish and verify the completed run locally as described in the
   [user guide](user-guide.md#step-4-generate-artifacts-and-dispatch-cicd).
2. Copy the publication, including `publication-manifest.json`, without changing
   its bytes to `published-fabric-workflows/<run-id>/<digest>` in the remote
   repository. The accelerator does not upload it. Follow your organization's
   data-handling and repository policies, and avoid Git filters or line-ending
   conversions that alter the files.
3. Ensure the selected branch or tag contains the publication and the updated
   trusted CI definitions and both verification scripts. Obtain the full commit
   SHA for that revision.
4. Enter the publication digest and expected commit SHA in the portal, or set
   `publication_digest` and `expected_commit` in the deployment request.

The service regenerates the run in a temporary directory, compares it with the
verified local publication, and dispatches the publication path and exact
manifest hash. Updated CI compares the expected SHA with the event and checkout,
then verifies the manifest and all publication files before deployment.
The publication directory name contains the canonical manifest digest; older
local publications may have differently formatted manifest bytes, so their
exact manifest hash can differ from that digest.

These are opt-in checks, not a signature or independent attestation. Protect and
verify the selected CI definition, checkout, and runner. A moving ref can select
an older or altered definition, and older GitLab jobs can ignore the variables.
Dispatch acceptance alone does not prove which files the remote job deployed.

## Shared prerequisites

Prepare these resources before configuring either provider:

1. A Microsoft Entra service principal.
2. A Fabric workspace on active capacity.
3. Fabric tenant settings that allow the service principal to call Fabric
   APIs.
4. Contributor or higher access for the service principal on the target
   workspace.
5. Generated definitions under `generated-fabric-workflows`, or an approved
   publication at the repository path described above.
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

### Create a pipeline with GitHub Actions

Use the manual
[`create-fabric-deployment-pipeline.yml`](../../.github/workflows/create-fabric-deployment-pipeline.yml)
workflow to create the deployment pipeline container and its ordered stages.
It uses the `dev` environment's existing Azure authentication secrets and the
self-hosted Windows X64 runner.

1. Enable the Fabric tenant setting **Service principals can create workspaces,
   connections, and deployment pipelines** for the deployment identity.
2. Open **Actions > Create Fabric deployment pipeline > Run workflow**.
3. Enter `pipeline_name` and an optional `pipeline_description`.
4. Enter the exact display names of the existing Development, Test, and
   Production workspaces. All three are required; create the workspaces and
   grant the deployment identity Admin access before running this workflow.
5. To give a team access to the pipeline, enter the configured Entra
   security-group name or an object ID in `pipeline_admin_group`. Name resolution
   uses `FABRIC_PIPELINE_ADMIN_GROUP_NAME` and
   `FABRIC_PIPELINE_ADMIN_GROUP_ID` repository variables; it does not require
   Microsoft Graph permissions. An arbitrary unconfigured name is rejected.
6. Leave `dry_run` set to `true` and review the proposed pipeline, assignments,
   and group access
   in the run summary. Rerun with `dry_run: false` to apply them.

The stages default to Development, Test, and Production, using the existing
`FABRIC_DEV_STAGE_NAME`, `FABRIC_TEST_STAGE_NAME`, and `FABRIC_PROD_STAGE_NAME`
repository variables when configured. The workflow exposes the verified
`pipeline_id` and `pipeline_name` as job outputs and in its summary.

An accessible pipeline with the exact same name is reused only when its stage
names and order match. When `pipeline_name` does not exist yet, the workflow
automatically reuses an existing pipeline if all requested workspaces are
already assigned to it in matching stages, leaving empty stages ready to
attach. No conflict-mode input is required. Existing descriptions, stage
visibility, and nonempty
workspace assignments are preserved. Mismatches fail without deleting or replacing
anything. A preview of a new name reports `WouldCreate` and has no pipeline ID.

The deployment identity needs Admin on all three workspaces and on a reused
pipeline. The workflow rejects ambiguous workspace names, requests to reuse a
workspace across stages, and conflicts in pipelines visible to the identity.
Fabric enforces assignment eligibility and rejects conflicts the workflow
cannot see. A matching existing assignment is skipped. Assignments are made
one at a time; if a later assignment fails, preview and rerun to resume without
undoing successful assignments.

The GitHub workflow does not support pipeline-only creation. It creates or
reuses the deployment pipeline together with all three required workspace
assignments.

The optional Admin group is added idempotently to newly created or reused
pipelines. Existing matching access is reported as `AlreadyAdmin`; dry runs
report `WouldAddAdmin` or `WouldAddAfterCreate`. The service principal must
already be pipeline Admin to grant access on a reused pipeline. No group
membership is modified.

Configure the standard name mapping once:

```powershell
gh variable set FABRIC_PIPELINE_ADMIN_GROUP_NAME `
  --repo <owner>/<repository> --body '<exact-group-name>'
gh variable set FABRIC_PIPELINE_ADMIN_GROUP_ID `
  --repo <owner>/<repository> --body '<group-object-id>'
```

The workflow does not create workspaces, move or unassign existing workspaces,
promote items, or overwrite `FABRIC_DEPLOYMENT_PIPELINE_ID`. Review and configure
that variable before using the promotion workflow. Preview does not prove that
the tenant permits creation or that Fabric will accept every assignment.

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
| Workflow filter | `*` | Workflow folder name, such as `02_low_west_sample`, or a relative-path wildcard, such as `alteryx-workflows/02_*` |
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

To use different labels, set the repository or organization variable
`DEPLOY_RUNNER_LABELS` to a JSON array, for example `["self-hosted", "Windows", "deploy"]`.
The deployment, pipeline-provisioning, and ALM promotion workflows all read it and
default to the labels above. CI jobs have their own `CI_RUNNER_LABELS`, so the runners that
hold Fabric credentials can stay separate from the runners that build pull requests.

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

GitLab supports Development artifact deployment, Deployment Pipeline
provisioning, and governed Test/Production promotion. The root
[`.gitlab-ci.yml`](../../.gitlab-ci.yml) defines shared manual inputs and
includes:

* [Artifact deployment](../../.gitlab/ci/deploy-fabric-artifacts.yml)
* [Deployment Pipeline creation](../../.gitlab/ci/create-fabric-deployment-pipeline.yml)
* [Fabric ALM promotion](../../.gitlab/ci/promote-fabric-alm.yml)

`FABRIC_OPERATION` selects `Deploy`, `CreatePipeline`, or `Promote`. `Deploy`
is the default so accelerator API dispatch remains backward compatible.

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
| `AZURE_CLIENT_ID` | Masked; Protected when `main` is protected | `dev`, `test`, `prod` |
| `AZURE_TENANT_ID` | Masked; Protected when `main` is protected | `dev`, `test`, `prod` |
| `AZURE_CLIENT_SECRET` | Optional fallback; Masked, Hidden, Protected | `dev`, `test`, `prod` |
| `FABRIC_DEPLOYMENT_PIPELINE_ID` | Protected | All or `dev`, `test`, `prod` |
| `FABRIC_DEV_STAGE_NAME` | Optional | All |
| `FABRIC_TEST_STAGE_NAME` | Optional | All |
| `FABRIC_PROD_STAGE_NAME` | Optional | All |
| `FABRIC_VARIABLE_LIBRARY_NAME` | Optional | All |
| `FABRIC_DEV_VALUE_SET_NAME` | Optional | All |
| `FABRIC_TEST_VALUE_SET_NAME` | Optional | All |
| `FABRIC_PROD_VALUE_SET_NAME` | Optional | All |
| `FABRIC_DEPLOYMENT_PLAN_ID` | Optional preview item ID | All |
| `FABRIC_PIPELINE_ADMIN_GROUP_NAME` | Optional configured group mapping | All |
| `FABRIC_PIPELINE_ADMIN_GROUP_ID` | Optional configured group mapping | All |

If variables are protected, protect the `main` branch so the deployment job
can receive them.

For OIDC, each job requests `FABRIC_OIDC_TOKEN` with audience
`$CI_SERVER_URL`. Configure the Entra federated identity issuer as the GitLab
origin, audience as the same GitLab origin, and subject for the protected
branch, for example:

```text
project_path:<group>/<project>:ref_type:branch:ref:main
```

When `AZURE_CLIENT_SECRET` is absent, the shared job template maps the GitLab
ID token to `AZURE_FEDERATED_TOKEN`. When the secret exists, the existing
client-secret path is retained.

Create `dev`, `test`, and `prod` GitLab environments. Protect the target
environments and configure allowed deployers. Configure deployment approvals
for `test` and `prod` when supported by the GitLab tier. The promotion job is
manual even when no approval rule is configured.

### Run manually

1. Open **Build > Pipelines**.
2. Select **New pipeline**.
3. Select `main`.
4. Choose `FABRIC_OPERATION`.
5. Complete the variables for that operation.
6. Run the pipeline.

For `Deploy`, select `TARGET`, `WORKFLOW_FILTER`, `CONFLICT_BEHAVIOR`, and
`DRY_RUN`. For `CreatePipeline`, provide the pipeline name and all three
existing workspace names; use `DRY_RUN=true` first. The result JSON and dotenv
outputs are retained for seven days.

For `Promote`, choose the target stage and `Selected` or `All`. Selected mode
requires exact name/type JSON and `DEPENDENCIES_REVIEWED=true`. The planning
job runs first and publishes `promotion-plan.json`. Review that artifact, then
start the manual `promote_fabric_alm` job. GitLab applies the target protected
environment and any configured deployment approval before execution.

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

