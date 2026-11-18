---
title: Deployment Strategy
description: Define Development bootstrap, Fabric-authoritative Git, and governed promotion
---

## Scope

Automated CI/CD deployment targets an explicitly specified Microsoft Fabric **`dev`** workspace via dispatch-only GitHub Actions (`.github/workflows/deploy-fabric-artifacts.yml`) or GitLab CI (`.gitlab-ci.yml`) calling `scripts/Deploy-FabricArtifacts.ps1`.

Existing items default to idempotent `Update` (`Fail` and `Skip` remain selectable). Dataflow Gen2, Notebook, and Data Pipeline definitions are read back after creation/update to verify all required parts, and runtime-ready Dataflow queries are validated via `executeQuery`.

## Fabric-authoritative Development

GitHub repositories can opt into Fabric-authoritative source control by setting
`FABRIC_SYNC_DEVELOPMENT_TO_GIT=true`. After a successful Development
deployment, `scripts/Invoke-FabricAlm.ps1` reads Fabric Git status and commits
all pending workspace changes to the connected branch.

The synchronization fails when the remote branch contains unapplied changes or
when Fabric reports a conflict. This prevents the automation from overwriting a
competing Git change.

## Promotion beyond Development

The manually dispatched `.github/workflows/promote-fabric-alm.yml` workflow
promotes one adjacent stage at a time:

1. Development to Test through the protected `test` GitHub environment.
2. Test to Production through the protected `prod` GitHub environment.

Each promotion requires:

1. Bound Fabric workspace connections and Lakehouse/Warehouse destinations.
2. Verified source-to-target row-count, schema, and business-rule semantic parity.
3. Environment-scoped Microsoft Entra Workload Identity Federation credentials.
4. Required GitHub environment reviewers and deployment branch restrictions.
5. A Fabric Deployment Pipeline with assigned adjacent workspaces.

When a Variable Library is configured, promotion selects and verifies the
target stage's active value set after the Deployment Pipeline operation
completes. The active value set remains workspace state and is not committed to
Git.

## Security & Operational Controls

- **Secretless OIDC Authentication**: `Deploy-FabricArtifacts.ps1` exchanges federated OIDC tokens (`api://AzureADTokenExchange`) with `AZURE_CLIENT_SECRET` retained only as an optional fallback.
- **Explicit Workspace Targeting**: `FABRIC_WORKSPACE_ID` is required at dispatch time with per-workspace concurrency serialization.
- **Native-Only Request Envelopes**: Scaffolds and unparsed workflows never emit `*-create-item.json` files.
- **Single Writer Per Branch**: Fabric is authoritative after Development bootstrap; external automation does not push competing item definitions to the connected branch.
- **Manual Promotion**: Test and Production promotion only run through `workflow_dispatch` and protected GitHub environments.
- **Stage-Specific Configuration**: Variable Library active value sets are selected and verified independently in each target workspace.
