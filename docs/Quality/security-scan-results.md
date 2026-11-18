---
title: Security Scan Results
description: Dependency, static-analysis, and platform security validation evidence
ms.date: 2026-11-08
---

| Scan | Command | Result |
|------|---------|--------|
| Python dependency audit | `uvx pip-audit --strict` | No known vulnerabilities (enforced in CI) |
| Web dependency audit | `npm audit --audit-level=high` | Zero vulnerabilities (enforced in CI) |
| Static analysis (SAST) | GitHub CodeQL (`python`, `javascript-typescript`), Ruff, and mypy | Enforced in CI and passed locally |
| Threat model | STRIDE review (`docs/Security/threat-model.md`) | Completed; OIDC federation & SDL controls implemented |

All Chrysalis SDL self-assessment prerequisites (STRIDE threat modeling, SAST, dependency vulnerability scanning, OIDC workload identity support, and customer-data sanitization) are implemented.
