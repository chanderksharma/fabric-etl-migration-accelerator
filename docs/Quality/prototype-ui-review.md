---
title: Prototype UI Replication Review
description: Browser navigation audit, implemented reference UI, and measured deviations
ms.date: 2026-11-07
---

## Reference and audit

The reference is [prototype.html](../../prototype.html), supplied explicitly
for browser analysis and UI replication. It was opened as a local browser page,
not embedded in the application.

Browser interactions inspected:

* Four desktop and four mobile navigation destinations
* All 34 reference workflow-row links
* All six workflow-drawer tabs and all six technical-register tabs
* Eighteen portfolio navigation controls, guide and breadcrumb navigation
* Four migration stages, capacity controls, filters and register pagination
* Graph search, zoom, fit, selection and workflow-to-evidence deep linking
* GitHub, SPN and bearer-token deployment layouts

The reference has no persistent native anchor links; its navigation is
implemented through buttons. External HTTP requests were blocked during
inspection. Live deployment/authentication submissions were not executed.

## Implemented application UI

The React application now uses the reference's paper sidebar, Migration Hub
brand, breadcrumb/header, theme tokens, metrics, two-column panels, tables,
planning cards, technical registers and six-tab workflow drawer.

The existing intake, recursive folder drop, confirmed snapshots, job recovery,
exports and guarded generation remain available. New assessment is accessible
from the sidebar scope card. Actual assessment results drive all figures.

Source graphs use verified, bounded workflow evidence. Original canvas
coordinates are retained when available; otherwise the view explicitly says
derived layout. Graph nodes support keyboard selection, search, pan, zoom and
fit. Risk and capacity displays are static or illustrative, not runtime claims.

## Measured visual checks

At a 1440 by 1000 viewport, the reference and application both measured:

| Surface | Reference | Application | Target tolerance |
| --- | --- | --- | --- |
| Sidebar width | 252 px | 252 px | 1 px |
| Header height | 68 px | 68 px | 1 px |
| Main title height | 48 px | 48 px | 1 px |
| Content horizontal padding | 32 px | 32 px | 1 px |

Light and dark themes were checked in the browser. Dark sidebar text was
`rgb(222, 222, 222)` and page background `rgb(61, 59, 58)`, matching the
reference tokens. All four application pages were checked at 390 by 844 with
no horizontal document overflow. Data/content differences prevent claiming
pixel-identical screenshots.

## Intentional deviations

| Reference behavior | Application behavior | Reason |
| --- | --- | --- |
| Sample 34 workflows and fixed metrics | Actual run values, including 32 workflows in the supplied estate | No fabricated assessment results |
| Reference wave allocation | Engine wave names/allocation retained | No frontend re-scoring or silent re-planning |
| Direct credentials and live deployment | Disabled credential fields and Deploy button; local dry-run only | No credentials or unauthorized external mutations |
| Static interpretation diagram | Labeled interpretation of captured source tools | No fabricated executable topology |
| No intake navigation | New assessment entry retained | Preserve usable input/confirmation flow |
| Unlimited register rendering | 50-row pagination and bounded graph evidence | Preserve large-estate responsiveness |

## Safety and contracts

Only the authorized CSS asset was extracted. Its source SHA-256 is recorded
in the stylesheet; tests reject remote imports, external CSS URLs and
script-like CSS constructs. No prototype authentication script was copied.

The read-only evidence API uses schema 1.0.0 with run/snapshot/workflow identity,
field allowlists, redaction before truncation, credential-bearing expression
withholding, response limits and `Cache-Control: no-store` on success/errors.
Client requests are abortable and identity-checked. The in-memory cache is
bounded to 20 entries; stale responses evict the affected run.

Review findings were remediated with automated unit and UI tests; architecture and implementation review trace IDs (`4c167933-f9ac-4c2e-8b79-7a3587705342`, `62b7567d-f3fb-4e0f-a5cf-a692056f13cc`) are preserved for audit provenance.

No source workflow was executed and no cloud deployment was submitted.
