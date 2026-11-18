---
title: Rollback Plan
description: Source, artifact, workflow, and Fabric dev rollback procedures
ms.date: 2026-11-08
---

## Triggers

Rollback is considered when a deployment definition fails readback, query
validation fails, a Notebook job fails, or parity evidence regresses.

## Procedure

1. Stop further workflow dispatches.
2. Record repository commit, GitHub run, Fabric item, and failure IDs.
3. Revert the generator or artifact commit through normal Git review.
4. Regenerate deterministic artifacts.
5. Redeploy the last accepted definition with Update.
6. Re-run readback and query or Notebook validation.
7. Record the rollback outcome and incident summary in the pull request and deployment run record.

Fabric deletion is not an automatic rollback action. It requires explicit owner
approval and a separate authorized operation.
