---
title: Accelerator Implementation Plan
description: Evidence-based delivery scope, work packages, acceptance criteria, and release gates
ms.date: 2026-11-17
ms.topic: reference
---

## Status and objective

Status: Baseline implementation and validation record. The analyst
application, shared intake/assessment, durable runs, guarded previews, and
exports have been implemented and tested. This does not by itself certify source/target parity, cloud deployment, or production readiness.

Build a deterministic Alteryx-to-Fabric accelerator that an analyst can use to
intake, assess, generate local conversion candidates, and export estate results.
Prepare an identity-based, dev-only deployment workflow with a dry run.
Deployment execution requires a named, approved dev workspace and authorization.

The authoritative architectural contract is
[System Architecture](../Architecture/system-architecture.md) and
[ADR-001](../Architecture/ADR-001-etl-source-adapters.md).
The presentation reference is
[the UI prototype](../../prototype.html).
Prior prototype iterations are treated as historical context, not an
automatically accepted implementation.

## Evidence and current gaps

Baseline verified on 2026-11-07 in the original repository:

| Surface | Command | Observed result |
| --- | --- | --- |
| Python lint | `uv run ruff check src\accelerator tests` | Passed |
| Python types | `uv run mypy` | Passed, 12 source files |
| Python tests | `uv run pytest` | 17 passed, 92% total coverage |
| UI lint | `npm run lint` in `apps\web` | Passed |
| UI tests | `npm test` in `apps\web` | 7 passed |
| UI build | `npm run build` in `apps\web` | Passed |

The Python test runner reports a Starlette/httpx deprecation warning. It is not
a failed check and does not justify an unrelated dependency change.

Focused synthetic-input probes also established:

| ID | Evidence | Delivery consequence |
| --- | --- | --- |
| GAP-01 | A ZIP with one XML workflow previews as one workflow but assesses as zero successes and one XML parse failure | Assessment must consume staged archive members, not archive bytes as XML |
| GAP-02 | The same ZIP bytes saved as `.yxzp` produce one assessment failure | Package containers need explicit intake expansion |
| GAP-03 | ZIP-mode assessment upload returns HTTP 422 | API and UI must accept the same source modes |
| GAP-04 | `tool assess` exits successfully with discovery output and no `assessments` field | Separate preview from actual assessment and define CLI output compatibility |
| GAP-05 | `Company.CustomFilter.CustomFilter` is classified as `dataflow` | Preserve plugin identity and use explicit registry matches |
| GAP-06 | UI state is held in React memory; the local-path mode is advertised but has no input control | Persist runs and implement or explicitly disable unavailable UX |
| GAP-07 | The inspected application exposes discovery/assessment but no graph compiler, generation/export routes, or deployment workflow | These are remaining milestones, not completed capabilities |
| GAP-08 | Existing objective summary still describes empty customer folders | Refresh derived intake evidence using the newly supplied sources |

Code evidence:
[application](../../src/accelerator/application.py),
[discovery](../../src/accelerator/discovery.py),
[assessment](../../src/accelerator/assessment.py),
[API](../../src/accelerator/api.py),
[CLI](../../src/accelerator/cli.py), and
[React application](../../apps/web/src/App.tsx).

## Scope boundaries

In scope:

* File, multi-file, ZIP, `.yxzp`, recursive folder, and local-path intake
* Immutable pre-run selection, explicit confirmation, bounded staging, and cleanup
* Neutral workflow graph, dependencies, data endpoints, and deterministic registry
* Assessment, effort estimates identified as estimates, migration waves, and risk
* Conservative Notebook and Dataflow Gen2 candidate generation
* Resumable local runs, incremental parsing, structured per-file failures
* Existing prototype-aligned UI, JSON/CSV exports, and analyst packaging
* Dev-only dry-run/deployment workflow preparation and mock-tested Fabric client

Out of scope:

* AI/LLM inference or generated Copilot prompts in the product
* Automatic conversion of every Alteryx tool or arbitrary embedded code
* Production promotion, production deployment, hotfixes, and tenant provisioning
* Reading source databases or executing imported workflows during assessment
* PBIP, XLSX, and additional legacy dashboard engines unless separately prioritized
* Hosted multi-tenant access; local-path endpoints must not be exposed remotely

Fabric Pipeline can be an assessment component recommendation when orchestration
is detected. Pipeline compilation is not an additional compiler milestone.
Unknown or redesign-only executable semantics must block automatic generation
even when other nodes have known mappings.

## Proposed architecture

Keep the existing Python/FastAPI application and React/Vite presentation layer.
Use `src\accelerator` as the installed Python package. Do not install or import
the legacy generic `src` package alongside it.

The shared application service owns:

1. Intake and an immutable source snapshot with logical paths and content hashes.
2. Safe XML parsing into a neutral, versioned graph.
3. Dependency resolution, registry classification, and assessment.
4. Durable run state and bounded work scheduling.
5. Local candidate generation and versioned artifact manifests.
6. Exports and an explicit, separately authorized deployment boundary.

CLI and API call the same use cases. The UI renders their shared schemas and
does not independently calculate fallback effort or target recommendations.

Use SQLite from the standard library for durable run metadata and JSON/CSV for
initial results. Introduce DuckDB/Parquet only if measured analytical workloads
require them. Add expression parsing or template dependencies only when the
accepted compiler subset needs them; do not add the whole candidate stack.
Use Python 3.13 as the minimum accelerator runtime and validate it in every
supported CI and container path.

Retain current React styling and navigation. Fluent UI adoption is optional,
not a prerequisite for completing the supplied design.

### Domain contracts

| Contract | Required content and invariant |
| --- | --- |
| Source snapshot | Selection ID, mode, logical paths, aliases, byte sizes, hashes, limits, and confirmation digest |
| Workflow graph | Full plugin identity, stable node IDs, anchors, edges, sanitized configuration, enabled state, endpoints, and dependency references |
| Tool registry | Explicit identity/alias mapping, assessment status, candidate targets, compiler coverage, notes, and version |
| Assessment | Stable workflow identity, counts, scoring/rules versions, estimated effort, unsupported semantics, dependency findings, and recommendation rationale |
| Run | ID, selected snapshot, queued/running/completed/failed/cancelled state, progress, worker lease, checkpoints, and typed failures |
| Artifact manifest | Source hash, graph/registry/compiler versions, bindings, output hashes, validation state, diagnostics, and ownership |
| Deployment plan | Approved dev workspace identity, immutable artifact manifest hash, dry-run result, required bindings, and explicit authorization |

Parsing can be cached by content hash and parser version. Dependency resolution
and assessment also depend on logical path, macro context, registry/rules
versions, and options. Preserve aliases when deduplicating bytes: identical
workflow bytes in different folders can resolve different macro references.
Never reuse a cached dependency-sensitive result using content hash alone.

### Legacy reuse assessment

Prior prototype architectures documented local-only source availability and conservative compiler boundaries.
Any reused modules and fixtures must become self-contained application-owned
files; CI must not require an ignored local `source` checkout.

| Candidate prior art | Reuse direction | Acceptance condition |
| --- | --- | --- |
| `services\input_intake.py` | Adapt aggregate budgets, package namespaces, collision guards, and snapshot behavior | New intake contract tests pass on Windows and Linux |
| `services\alteryx_parser.py`, `models\inventory.py` | Port neutral graph and sanitized dependency extraction | Validate root, namespaces, IDs, disabled branches, and malicious XML |
| `services\tool_mapping.py`, `tool_signals.py`, `source_contracts.py` | Reuse conservative identity and execution-semantics rules | Unknown custom plugins cannot gain support by suffix |
| `services\fabric_codegen.py`, `dataflow_codegen.py`, relational helpers | Port coherent compiler dependencies, not isolated snippets | Golden tests preserve fail-closed behavior and diagnostic states |
| `services\generation_status.py`, `migration_evidence.py` | Reuse provenance and stale-source validation concepts | Changed source, options, registry, or bindings invalidate outputs |
| `exporters` and ownership helpers | Reuse only needed JSON/CSV and manifest behavior | Exports remain deterministic and unrelated files survive reconciliation |
| Flask UI, generic agent wrappers, PBIP, prompt generation | Do not port into the primary product | No second application engine or AI product dependency |

Check ownership, license, transitive dependencies, and test compatibility before
porting. Legacy documentation is not proof that the imported implementation or
generated candidates have passed validation in this workspace.

## Work packages and dependency graph

Each ID is an intended Azure Boards work item. Local-only work remains journaled
until tracker controls are available. Owners are roles, not assigned people.

| ID | Ring | Owner | Prerequisites | Deliverable |
| --- | --- | --- | --- | --- |
| WP-00 | 0 | Principal Architect | None | Canonical objective, source inventory, acceptance traceability, updated intake evidence |
| WP-01 | 1 | Solution Architect / Plan Reviewer | WP-00 | Reviewed architecture, contract versions, prioritized compiler subset, WBS, risks, and approved bounds |
| WP-02 | 2 | Intake implementation lead | WP-01 | Shared secure source snapshots and ZIP/package/folder intake |
| WP-03 | 2 | Parser implementation lead | WP-02 | Neutral graph, exact registry, dependency inventory, shared assessment |
| WP-04 | 2 | Application implementation lead | WP-03 | SQLite jobs, incremental processing, progress, cancellation, restart recovery |
| WP-05 | 2 | Compiler implementation lead | WP-03 | Fail-closed Notebook and Dataflow candidate packages with manifests |
| WP-06 | 2 | UI / application implementation lead | WP-04, WP-05 | Prototype-aligned UI, shared CLI/API contracts, generation and JSON/CSV exports |
| WP-07 | 2 | Delivery implementation lead | WP-06 | Analyst container/launcher, mock-tested deployment client, dev-only workflow and dry-run contract |
| WP-08 | 3 | Independent reviewers / Test Engineer | WP-07 | Integration, regression, compiler parity evidence, benchmark, OSS disposition, and independent reviews |
| WP-09 | 4-5 | Release owner | WP-08, required approvals | Release packet and staged readiness; no unauthorized deployment |

WP-04 and WP-05 can proceed independently after WP-03. UI shell work can begin
against the reviewed WP-01 contracts, but WP-06 cannot close until jobs,
assessment, generation, and exports work together.

Use at most five Research/Plan/Implement/Review iterations per approved work
package envelope. Stop and report at that bound. Do not interpret the bound as
permission to waive review, widen scope, or close a failing ring.

## Acceptance criteria by package

### WP-00 and WP-01

* Every source-backed requirement has an ID, work package, scenario, and validation method.
* Preserve raw imported inputs; refresh derived evidence rather than rewriting source intent.
* Record architecture and scope decisions with authority, accountability, and alternatives.
* Obtain plan and architecture review evidence before implementation begins.
* Record unresolved dev workspace identity and real-data benchmark availability as blockers.

### WP-02

Proposed initial safety defaults retain the current per-workflow and archive
ceilings while adding whole-request budgets. These are limits, not benchmark
targets; WP-01 must review them before implementation.

| Budget | Proposed initial ceiling | Enforcement |
| --- | --- | --- |
| Browser request payload | 100 MiB combined uploaded bytes | Streaming total, not a per-file allowance multiplied by file count |
| One XML workflow | 100 MiB | Declared size and actual bytes read |
| One intake archive expansion | 2 GiB across all selected containers | Separate cumulative declared and streamed counters; either exceeding the ceiling rejects the intake |
| Archive entries | 10,000 across all selected containers | Count nested package entries against the same budget |
| Compression ratio | 100:1 per archive entry | Reject nonempty entries with zero compressed size |
| Archive nesting | ZIP plus one `.yxzp` expansion | Explicit skip reason for deeper containers |

Local-path intake avoids the browser transport budget, not the per-file,
archive-expansion, or entry-count limits. Count every materialized layer,
including nested package bytes, toward expansion accounting.

* A direct file, folder, ZIP, and `.yxzp` containing the same XML produce equivalent accepted content identities.
* Multiple packages with matching basenames retain unique logical paths and macro contexts.
* ZIP containing `.yxzp` is supported within a documented single package-expansion level; deeper containers are skipped explicitly.
* Enforce aggregate compressed, expanded, entry-count, per-file, and compression-ratio budgets on declared and streamed bytes.
* Check traversal, Windows-reserved names, symlinks, junctions, encrypted archives, duplicate names, and case collisions.
* Do not resolve a root symlink before checking whether it is forbidden.
* No symlink/junction traversal, source execution, or overwrite through upload name collisions.
* Unsupported files and rejected members have stable reasons; malformed files do not abort unrelated workflows.
* Cleanup completes after success, rejection, cancellation, and worker failure, subject to the documented retained snapshot policy.
* Confirmation binds to immutable accepted content; changed local files require a new preview.

Temporary extraction trees must be removed when processing ends. Normalized,
confirmed workflow snapshots retained for resumable runs are separate managed
storage, not abandoned extraction directories. Document their disk budget,
retention lifecycle, explicit removal controls, and exclusion from Git.

### WP-03

* Reject non-Alteryx roots, DTD/entities, missing/duplicate node IDs, invalid anchors, and inconsistent graphs with typed findings.
* Inventory data endpoints and macros statically without connecting to them or exposing secrets.
* Full plugin identity governs mapping; annotations and disabled nodes do not falsely increase executable coverage.
* Unsupported tools or configuration are visible in assessment and block corresponding conversion.
* Estimates are reproducible, versioned heuristics, not measured migration durations.
* Preserve all logical paths and aliases without leaking disposable staging paths into reports.

### WP-04

* Processing uses a bounded worker count and does not monopolize the API event loop.
* Restart resumes unfinished work and preserves completed results; expired worker leases can be recovered.
* SQLite atomically claims work and commits result/checkpoint transitions; two workers cannot claim the same live lease.
* The first release runs on one local host, not a distributed scheduler; leases fence stale workers after recovery.
* Cancellation is explicit, checkpointed, and stops new scheduling while cleanup remains reliable.
* Incremental runs reparse only changed bytes or invalidated parser versions.
* Registry, rules, options, macro context, and binding changes invalidate dependent results.
* Failures include workflow identity, stable code, actionable detail, and run status.

### WP-05

* Define the first compiler subset using inventory evidence and legacy fixtures; publish its exact supported semantics.
* Each supported tool/configuration has positive and negative golden tests for both target choices where applicable.
* Block arbitrary embedded Python/R, unknown tools, unsupported aggregates, ambiguous flags, graph branches, and unproven expression behavior.
* Distinguish `blocked`, `preview_unvalidated`, `generated_unvalidated`, `bound`, and `validated` states.
* A preview or generated shape is never labeled equivalent, executable, validated, or deployable merely because it parses.
* Preserve source hashes, diagnostics, input/output binding requirements, and compiler versions in manifests.
* Validate synthetic transformation semantics independently; do not execute imported code or customer datasets.
* Reconcile only generator-owned outputs and preserve unrelated local files.

### WP-06

* Browse, drag/drop, ZIP, folder, and enabled server-local path use the same confirmed snapshot.
* Show rejected/skipped items, upload limits, progress, partial failures, restart recovery, and cancellation.
* Confirming ZIP intake successfully reaches assessment rather than a UI placeholder or HTTP 422.
* Refreshing the browser restores a selected run and results; stale requests cannot overwrite a newer selection.
* Portfolio, workflow details, migration plan, and technical details render engine-produced values.
* Generation controls and exports have real backend outcomes, explicit errors, and visible validation states.
* Theme switching works; keyboard navigation, focus, labels, status announcements, and contrast receive accessibility checks.
* Hosted mode disables server-local paths; local deployment uses loopback and protects state-changing endpoints from untrusted origins.
* Keep the approved visual direction; require evidence before claiming pixel parity with the prototype.

### WP-07

* One documented launcher/container serves built React assets and API on the same origin.
* An analyst can perform intake through exports without a separate frontend development server.
* No secrets enter source, images, generated code, logs, or reports.
* Deployment fails closed when the approved dev workspace identity is absent or differs from the request.
* Dry run validates target identity, artifact hashes, bindings, candidate state, and planned changes without Fabric mutation.
* Fabric calls use workload identity or service principal configuration from the CI environment, bounded concurrency, and bounded retry/backoff.
* Persist polling/resume state and avoid duplicate creates after ambiguous network failures.
* Normal CI never deploys automatically; dev deployment is explicitly gated and cannot target another environment.
* API client and deployment policy tests use mocks; actual cloud calls require explicit authorization.

### WP-08 and WP-09

* All lint/type/build checks and existing behavioral tests remain green.
* Maintain at least 80% business-logic coverage; cover every public endpoint and failure contract.
* Run Windows/Linux intake tests, UI integration tests, compiler golden tests, and restart/cancellation tests.
* Obtain independent code, architecture, quality, and security/OSS review evidence through approved routing.
* Real runtime parity requires an authorized isolated source/target test environment; unavailable evidence remains a blocker.
* Release notes name supported compiler semantics, rejected cases, known limitations, rollback, and operator steps.
* Production remains out of scope; do not close gates based on placeholders or self-review alone.

## Benchmark and completion evidence

Proposed benchmark protocol, not an achieved result or a customer-approved SLA:

1. Obtain an authorized, redacted sample of approximately 500 real workflows with representative tools, macros, packages, failures, and complexity bands.
2. Use a separate 5,000-workflow synthetic fixture set for scheduling and incremental-run mechanics; do not use duplicates to claim real-estate coverage.
3. Record hardware, OS, runtime versions, worker count, input bytes, graph counts, and registry/compiler versions.
4. Run equivalent folder and ZIP inputs, cold runs, unchanged incremental runs, single-file changes, cancellation, and process restart.
5. Measure wall time, peak memory, disk expansion, throughput, failure isolation, parsing cache hits, classification coverage, compiled-node coverage, and diagnostic counts.
6. Verify byte-stable normalized results and unchanged semantics across repeated runs; exclude timestamps and run IDs from deterministic comparisons.
7. Report unsupported coverage honestly; compare accepted candidate outputs against authorized reference results before claiming conversion parity.

Performance targets must be agreed after the pilot on a documented analyst
machine. Do not invent timing, cost savings, or conversion percentages from the
available source documents.

Primary existing validation commands:

```powershell
uv run ruff check src\accelerator tests
uv run mypy
uv run pytest --cov-fail-under=80
Set-Location apps\web
npm run lint
npm test
npm run build
```

Future integration and benchmark selectors will be added with their tests.
Existing commands alone cannot certify features that do not yet exist.

## Risks and external dependencies

| Risk or blocker | Handling | Closure evidence |
| --- | --- | --- |
| Governed planner previously denied filesystem access as outside-workspace | Provide complete sanitized plan context to reviewers without filesystem access; never bypass denial | Actual reviewer result and producer-model attestation |
| Main-chat producer initially unknown | Resolved using current-session metadata and owner-attested governed routing | Verified `gpt-6.1-sol` producer and different-provider reviews |
| Legacy full source is local-only and uses another package layout | Port reviewed application-owned modules and fixtures with provenance | CI succeeds without the ignored source checkout |
| No named approved Fabric dev workspace or identity configuration supplied | Implement policy and mock tests; defer real deployment | Workspace ID, identity configuration, dry run, explicit authorization |
| Real 500-workflow sample and parity environment are not confirmed | Prepare reproducible harness and synthetic tests; do not claim real benchmark completion | Authorized dataset and measured report |
| Broad Alteryx semantics exceed initial compiler coverage | Prioritize an explicit subset; fail closed with redesign diagnostics | Tool/configuration coverage report and golden/parity evidence |
| Macro references make content-only deduplication semantically unsafe | Retain logical aliases and resolve dependencies in context | Context-sensitive deduplication and invalidation tests |
| Browser uploads and archive expansion exceed workstation resources | Aggregate limits, local-path mode, bounded workers, and observability | Limit, benchmark, restart, and cancellation evidence |
| Local-only Git mode has no Azure DevOps origin | Journal intended work items; prepare CI but do not imply connected tracker gates passed | Connected remote controls and required gate review |

This plan does not advance any ring. Under the local-only tracking rules,
Implementation can continue within explicitly approved bounds, but gate closure
and external release claims must remain separate.

## Review handoff

Review against scope completeness, dependencies, feasibility, shared contracts,
archive/package boundaries, context-aware caching, fail-closed conversion,
accessibility, packaging, dev-only deployment, and evidence integrity.

The [audit findings disposition](../Quality/audit-findings-log.md) records
findings, remediation evidence, and verification status.
