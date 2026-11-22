---
title: Audit Findings Log
description: Architecture, code, test, and security review disposition log
ms.date: 2026-11-22
---

| ID | Source | Severity | Finding | Owner | Due | Disposition |
|----|--------|----------|---------|-------|-----|-------------|
| AF-01 | Code/Test | Major | Sanitized synthetic parity corpus | Test Manager | 2026-11-15 | Resolved; hermetic synthetic Alteryx, PowerCenter, and IDMC fixtures tracked in Git |
| AF-02 | Code/Test | Major | Unsupported custom workflows remain explicit scaffolds | Compiler Lead | 2026-11-15 | Resolved by design; explicitly non-deployable scaffolds |
| AF-03 | Test | Minor | Container runtime verification on target host | Test Engineer | 2026-11-30 | Tracked for optional container deployments |
| AF-04 | Security | Major | Migrate SPN deployment auth to Entra OIDC federation | Security Owner | 2026-11-15 | Resolved in `Deploy-FabricArtifacts.ps1` and `deploy-fabric-artifacts.yml` |
| AF-05 | Architecture | Major | Six operational ADRs missing | Solution Architect | 2026-11-08 | Resolved in ADR-L09..L14 |
| AF-06 | Code | Major | Automated SAST and dependency audit in CI | Security Reviewer | 2026-11-15 | Resolved via CodeQL, `pip-audit`, `npm audit`, and Dependabot |
| AF-07 | Documentation | Minor | External work-tracker decoupling for InnerSource | Program Manager | 2026-11-15 | Resolved; personal ADO references removed |
| AF-08 | Capacity | Major | Capacity model uses narrow Alteryx-to-Dataflow calibration and unconfirmed operating defaults | Platform Architect | 2026-12-15 | Mitigated; scope exclusions and modeled coverage are explicit, leadership SKU is gated on confirmed inputs, and pilot validation in Fabric Capacity Metrics is required |
| AF-09 | Security/CI | Major | The CI dependency audit (`uvx pip-audit --strict`) scanned pip-audit's own tool environment (29 packages), not the project's locked dependencies. The first correct audit found `pytest` 8.4.2 (PYSEC-2026-1845) and `tornado` 6.6 (CVE-2026-126347), both development-only | Security Reviewer | 2026-11-30 | Resolved in `ci.yml`, which audits the exported lock, and by locking `tornado` 6.6.1 and `pytest>=9.0.3,<10`; confirm on the first CI run after merge |
