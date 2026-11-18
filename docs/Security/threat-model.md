---
title: Accelerator Threat Model
description: STRIDE analysis for intake, GitHub dispatch, Fabric Git, and governed promotion
ms.date: 2026-11-17
---

## Trust boundaries

| ID | Boundary | Data | Controls |
|----|----------|------|----------|
| TB-01 | Browser to local API | Files, run commands | Loopback, trusted host, same-origin token |
| TB-02 | Uploaded archive to parser | Untrusted XML and packages | defusedxml, traversal, size, ratio, symlink limits |
| TB-03 | Local app to GitHub | Dispatch inputs | Repository URL validation, existing workflow, explicit auth mode |
| TB-04 | GitHub runner to Fabric | Definition envelopes and Entra OIDC / SPN token | Dev environment, Entra OIDC workload identity federation (optional SPN secret fallback), explicit workspace ID, readback validation |
| TB-05 | Generated artifact to execution | M or PySpark code | Native-only create-item output, diagnostics, parity requirement |
| TB-06 | Fabric Development workspace to GitHub | Fabric item definitions and configured Git credential | Fabric Git connection, single-writer branch, remote-change and conflict checks |
| TB-07 | GitHub runner to Fabric ALM | Stage IDs, Variable Library state, and deployment token | Manual workflow dispatch, protected environments, adjacent-stage validation, target-state readback |

## STRIDE analysis

| Category | Threat | Mitigation | Status |
|----------|--------|------------|--------|
| Spoofing | Untrusted browser or repository identity | Trusted hosts, CSRF token, GitHub auth, repo validation | Mitigated |
| Tampering | Changed local source after preview | Immutable snapshots and source hashes | Mitigated |
| Repudiation | Untracked deployment action | GitHub run ID, commit SHA, Fabric item/job IDs | Mitigated |
| Information disclosure | Secrets in artifacts or logs | `.env` ignored, OIDC federation (secretless by default), redaction, server-only tokens | Mitigated |
| Denial of service | Archive bombs or excessive workflows | Aggregate budgets, bounded workers, cancellation | Mitigated |
| Elevation of privilege | Unauthorized Test or Production promotion | Protected GitHub environments, Deployment Pipeline admin role, workspace roles, and adjacent-stage validation | Mitigated |
| Tampering | Remote Git changes overwritten by workspace synchronization | Fail closed on remote-only changes and Fabric Git conflicts | Mitigated |

## SDL security controls

| ID | Control | Implementation | Status |
|----|---------|----------------|--------|
| SEC-01 | Entra Workload Identity Federation (OIDC) | `scripts/Deploy-FabricArtifacts.ps1` and `deploy-fabric-artifacts.yml` (`id-token: write`); `AZURE_CLIENT_SECRET` retained only as optional fallback | Implemented |
| SEC-02 | Static application security testing (SAST) | GitHub CodeQL (`python`, `javascript-typescript`) in `.github/workflows/ci.yml` | Implemented |
| SEC-03 | Credential & customer-data hygiene | SQLite/log redaction, synthetic-only repository fixtures, zero hardcoded workspace/tenant GUIDs | Implemented |
| SEC-04 | Dependency & supply-chain scanning | Automated `pip-audit --strict`, `npm audit --audit-level=high`, and `.github/dependabot.yml` | Implemented |
| SEC-05 | Fabric Git source control | Configured Git credential, single-writer branch, status verification, conflict rejection | Implemented |
| SEC-06 | Governed Fabric promotion | Manual dispatch, protected `test` and `prod` environments, stage adjacency, and Variable Library state verification | Implemented |

The self-hosted runner is trusted infrastructure. It must not execute untrusted
fork code with deployment secrets. Local `gh-cli` authentication is restricted
to development and must be disabled in production.

Production promotion remains manual and requires configured environment
reviewers, Fabric Deployment Pipeline permissions, and parity approval.
