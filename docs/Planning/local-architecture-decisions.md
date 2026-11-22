---
title: Local Architecture Decisions
description: Bounded implementation decisions and requirement-to-test traceability
ms.date: 2026-11-22
---

## Scope

This architecture decision record captures bounded local implementation and CI/CD deployment guardrails for the **Microsoft Fabric ETL Migration Accelerator**. Independent plan and architecture review conditions are enforced as engineering invariants.

## ADR-L01 Independent implementation

Implement application-owned modules under `accelerator`. No imported legacy
code is copied and no runtime import depends on its ignored checkout.
The existing FastAPI and React application remain the product entry points.

## ADR-L02 Neutral graph

Retain full plugin identity, stable node IDs, edges, dependencies, and graph
schema version. Validate Alteryx XML before scoring. Unknown executable tools
are retained as manual redesign, not classified through arbitrary suffixes.
No data source or embedded workflow code is executed.

## ADR-L03 Durable local state

Use SQLite WAL and short atomic claims with fencing epochs. Store immutable
confirmed workflow snapshots in managed local state outside source control.
Check cancellation between bounded workflow units. Recover interrupted claims
only after their lease expires. Refuse unsupported database schema versions.

## ADR-L04 Compiler boundary

The first compiler subset is a single linear tabular chain of InputData or
TextInput, numeric Filter, Select, and terminal OutputData or Browse.
Unsupported tools, options, branches, and dependencies fail closed.
All emitted code is guarded `preview_unvalidated`; no local operation can
promote it to validated or construct a cloud create request.

## ADR-L05 Local API

Bind the analyst launcher to loopback. Enforce trusted hosts and same-origin
browser mutations with a session token. Local paths are explicit analyst
selections, not a hosted file browser; reject UNC and linked/reparse roots.
Temporary archive staging is cleaned after use. Confirmed snapshots remain
until the analyst removes the managed state directory while the app is stopped.

## ADR-L06 Deployment dry run

Keep deployment planning a pure, network-free module. Missing or mismatched
approved dev identity and unvalidated candidates block the plan. No real
Fabric deployment or production promotion is implemented in this local slice.

## ADR-L07 Native component routing

Route native Dataflow Gen2 first, then native Fabric Notebook. Pipeline or mixed
orchestration requires explicit native components and dependencies. Scaffolds
are design evidence only and never receive create-item envelopes.

## ADR-L08 Deterministic and non-AI product scope

The product performs deterministic parsing, assessment, code generation, and
deployment planning. It does not call AI/LLM services or make autonomous
production decisions. Generated outputs remain unvalidated until parity
evidence is accepted.

## ADR-L09 Dispatch-only GitHub integration

The UI backend dispatches an existing workflow and does not create repository
content or monitor runs. GitHub Actions owns deployment execution and audit.

## ADR-L10 Local and production GitHub authentication

Local development may use an explicitly enabled `gh-cli` mode and the active
developer token. Production and multi-team use requires a repository-scoped
GitHub App and allowlist. Local mode is never a production credential path.

## ADR-L11 Self-hosted Windows runner

GitHub-hosted runners are unavailable. Deployment uses the self-hosted Windows
X64 runner. The runner must be patched, isolated, monitored, and restricted to
trusted repositories and dev credentials.

## ADR-L12 Idempotent deployment updates

Deployment defaults to Update when a same-name item exists. Fail and Skip remain
explicit options. Duplicate same-name items fail closed.

## ADR-L13 SPN query validation

Fabric rejects SPN-triggered Dataflow refresh. Deployment verifies definition
readback and evaluates the saved query through `executeQuery`, recording
`SPNQueryValidated`. This is not refresh materialization or parity approval.

## ADR-L14 Semantic Notebook stage names

Generated Notebooks use sanitized Alteryx annotation names and separate
markdown, import, transformation, and output cells. Raw graph identifiers are
internal and are not the user-facing code contract.

## ADR-L15 Fabric-authoritative Development

Deterministic REST deployment remains the Development bootstrap path. After
validation, the Fabric Development workspace becomes authoritative and commits
all pending workspace changes to its connected Git branch. Synchronization is
repository-variable gated and fails when Fabric reports remote-only changes or
conflicts.

## ADR-L16 Manual adjacent-stage promotion

Test and Production promotion use a Fabric Deployment Pipeline and only run
through manual GitHub workflow dispatch. Each promotion moves content forward
by exactly one adjacent stage and uses a protected `test` or `prod` GitHub
environment for approval and environment-scoped credentials.

## ADR-L17 Stage-specific Variable Library state

Variable Library definitions move with supported Fabric items. The active value
set remains workspace item state, so promotion selects and reads back the
target stage value set after the Deployment Pipeline operation completes.

## ADR-L18 Cached generation jobs and neutral artifact projection

Keep synchronous generate and preview as the file-writing paths. Add durable
generation jobs that compute and cache candidates without calling the artifact
writer. Project each cached candidate into `ArtifactSet` for a future target
writer, and leave `files` empty until that writer owns the bytes.

Schema 7 appends `generation_jobs`. Jobs use the same lease-epoch fencing as
assessment runs. An unexpected fault in one workflow becomes a blocked
candidate and is not cached. `OSError`, `sqlite3.Error`, and `ValueError`
still fail the estate or the job. Plugin registration treats a missing
`spi_version` as `1.0.0` and rejects an incompatible declaration. This decision
does not split `RunService`, rewrite the compilers, or connect plugin
generation to the portal.

## Requirement-to-test traceability

| Requirement | Validation |
| --- | --- |
| ZIP/package assessment | `test_archive_assessment_reads_members`, `test_nested_package_and_bad_workflow_are_isolated` |
| Shared actual CLI assessment | `test_cli_assess_returns_actual_assessments` |
| Exact registry identity | `test_custom_plugin_is_not_classified_by_suffix` |
| XML safety | `test_wrong_root_and_entities_are_typed_parse_failures` |
| Safe archive names | `test_windows_unsafe_archive_names_are_rejected`, `test_case_colliding_archive_members_are_rejected` |
| API ZIP assessment | `test_zip_upload_can_be_confirmed` |
| Guarded candidates | `test_candidate_generation_is_guarded_and_non_deployable`, `test_generation_blocks_unknown_semantics` |
| Immutable snapshots and durable results | `test_snapshots_jobs_and_exports_survive_reopening` |
| Cooperative cancellation | `test_cancelled_run_is_not_executed` |
| Fail-closed dev dry run | `test_dry_run_cannot_approve_unvalidated_candidates` |
| Fabric-authoritative Git synchronization | `test_fabric_alm_script_fails_closed_and_uses_native_alm_apis` |
| Manual environment-gated promotion | `test_fabric_alm_promotion_is_manual_and_environment_gated` |
| Cached generation jobs do not write files | `test_generation_job_caches_candidates_without_writing_artifacts` |
| One generation fault does not drop the estate | `test_mixed_estate_keeps_the_good_workflow_and_reraises_os_error` |
| SPI handshake | `test_spi_handshake_rejects_only_an_incompatible_declaration` |
| Sample-estate compiler digest | `test_sample_estate_digest_matches_the_golden_fixture` |

This matrix is extended with implementation tests. Existing tests alone do not
prove real-estate performance, source/target parity, or production readiness.
