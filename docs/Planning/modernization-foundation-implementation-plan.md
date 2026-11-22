---
title: ETL Modernization Foundation Implementation Plan
description: Phased implementation plan for correctness, portability, and pluggable ETL modernization
ms.date: 2026-11-22
ms.topic: reference
---

## Objective

Evolve the existing modular monolith into a portable ETL modernization accelerator.
Keep deterministic parsing, fail-closed compilation, traceability, and existing Fabric
workflows while making source and target extensions usable across the full application.
This plan supplements the earlier [pluggable architecture plan](./pluggable-architecture-implementation-plan.md)
with the findings from the subsequent implementation review.

## Initial implementation status

The implemented slices isolate ZIP downloads by request, restrict candidate ZIPs to
the current write's candidates, classify neutral issues per node, snapshot extracted IDMC exports, and
reject incompatible IR in Fabric compilation and evaluation. Neutral assessment rules
are version `1.0.1`; an operation can have separate inventory entries for different
classifications. Unknown operations are classified for manual review. XML intake checks
size before reading its bounded identification header. Artifact writing reuses compilation
results across target plans, workflow bundles, and deployment resolution.
Alteryx and PowerCenter adapter probes read at most 64,000 bytes for identification.
The run scheduler keeps at most four assessments in flight, fills free worker slots
without waiting for a full batch, and preserves result ordering. Cancellation stops
new scheduling after the worker observes it; already running parsers are not interrupted.
An opt-in local publication writes all target artifacts in a staging directory and
atomically publishes them under the run ID and a manifest digest. Publication
verification checks every artifact and rejects modified or extra files. The local API
and CLI can create and verify publications; the API can download a deterministic ZIP
containing only manifest-listed files. Legacy shared output and CI dispatch do not use
this publication by default.
Artifact writing rejects same-target logical-ID and case-insensitive output-path
collisions within a candidate set before publishing files. Existing Fabric logical
IDs are unchanged pending a migration.
The Fabric portal also prevents selecting an unintegrated target for Fabric generation
and disables generation and deployment when the capability catalog is unavailable.
The registry can evaluate canonical assets through an evaluate-only provider with
capability and IR checks. Provider metadata is checked both when listing and when
requiring a capability. The local API exposes separate, persisted target
evaluations and an automatically persisted neutral baseline for completed runs;
existing assessment results remain unchanged. The IR and neutral assessment contracts
also accept external source identifiers in IR `1.1.0` and use a generic workload profile.
Existing built-in sources retain IR `1.0.0`. Fabric
rejects unrecognized sources until their semantics are certified. Adapters with declared
extensions can participate in local-file and archive member discovery and neutral runs.
The portal offers separate installed-plugin intake, neutral assessment, and evaluation
with registered evaluate-capable targets; it does not offer plugin target generation
or deployment. External snapshots bind the
selected adapter identity and declared adapter, parser, registry, and rules versions;
changes require a new preview. Earlier external snapshots without component versions
also require a new preview. Built-in assessment cache keys include the currently
registered source adapter, parser, registry, and rules versions; older snapshots
remain readable and are reassessed when these versions change. Provider and
configuration cache invalidation remain incomplete. The main CLI exposes `assess-neutral` alongside the existing
Fabric-specific `assess` command.
An independently packaged Databricks example provides manual-review-only evaluation;
it does not implement Databricks semantics, generation, or deployment.
An independent synthetic SSIS adapter demonstrates bounded metadata extraction and
local neutral runs; it does not interpret SSIS semantics.

Portal previews and dry runs use isolated temporary directories. Deployment requests
can also opt into isolated local planning while preserving the original remote
artifact path. The default deployment path and legacy generation API still use a
shared root and are not transactionally isolated, so concurrent writes and
same-path overwrites remain open. Deployment requests may
optionally ask updated trusted CI definitions to compare the event and checkout
commit with an expected SHA. An optional publication digest also checks regenerated
local artifacts and asks updated CI to verify the exact remote manifest and files.
The operator must copy the publication to the remote repository first. These checks
do not enforce the presence of trusted guards at a moving ref and do not establish
independently attested remote provenance.
Provider-wide compatibility enforcement, logical-ID
migration, deployment provenance, and the remaining phases are also incomplete.

## Guardrails

* Preserve current APIs and Fabric behavior unless an explicit versioned migration is defined.
* Keep unsupported semantics as diagnostics or scaffolds, never runnable-looking output.
* Do not execute source expressions or treat installed Python plugins as sandboxed.
* Keep target-neutral assessment separate from target evaluation and capacity.
* Avoid a wholesale rewrite, a universal transpiler, and premature microservices.
* Keep customer data, credentials, and tenant-specific identifiers out of fixtures and commits.

## Phase 1: Correctness and artifact integrity

1. Restrict candidate ZIP contents to the current write's candidates and test consecutive
   runs against a shared artifact root. Preserve existing ZIP names and metadata.
2. Classify issues per node before aggregating neutral assessment. Version changed
   assessment rules and test mixed healthy and problematic nodes.
3. Design immutable run-scoped artifact publication, manifest-based packaging, and
   atomic publication. Cover concurrent writes, same-path runs, and failed publication.
   The ZIP membership change alone does not provide transactional isolation.
4. Define stable target logical identities from source namespace, native asset identity,
   and artifact kind. Plan migration for already deployed items before changing IDs.
5. Support extracted IDMC directories in durable snapshots with bounded, secure,
   deterministic copying and matching hash verification.
6. Reject unsupported IR versions before provider calls. Define compatibility semantics
   and cover evaluator, compiler, and other lifecycle entry points.
7. Classify unrecognized operations conservatively after inventorying built-in adapter
   operation vocabularies. Test diagnostics and existing supported operations.
8. Bind deployment to an immutable repository revision and artifact digest, and verify
   provenance in CI without moving cloud execution into the local service.

Exit gate: cross-run contamination, identity collisions, scoring errors, unsupported
versions, and extracted-directory intake have regression coverage. Existing delivery
behavior and documented deployment compatibility are verified.

## Phase 2: Runtime and assessment boundaries

1. Store one target-neutral source assessment and separate per-target evaluations,
   including evidence, residual effort, capacity, and validation status.
2. Unify assessment mode semantics across CLI, API, and portal; retain compatibility
   adapters for existing Fabric responses and saved runs.
3. Define typed, independently optional provider capabilities for evaluation, capacity,
   compilation, validation, and deployment planning. Keep delivery transport separate.
4. Pass platform identity and capability through API requests, execution, caching,
   errors, and UI controls. An evaluate-only provider must not enable generation.
5. Replace source-specific runtime branches with registry-driven source identity,
   discovery, staging, parsing, and workload profile contracts.
6. Specify plugin precedence, duplicate registration errors, version compatibility,
   trusted installation, and contract-test requirements.
7. Progressively model supported expression and control-flow semantics in the IR;
   preserve unknown source constructs and diagnostics without guessing.

Exit gate: the same snapshot and assessment mode yield consistent baseline facts across
entry points, and a provider with partial capabilities cannot invoke Fabric implicitly.

## Phase 3: Efficiency and operational quality

1. Reuse a versioned normalized package and compiled target results per snapshot.
   Include actual adapter, provider, IR, rules, configuration, and compiler versions in
   cache keys and retain explicit invalidation.
2. Build deployment plans from existing compilation results. Measure parse and compile
   counts and estate-scale runtime before and after the change.
3. Replace batch barriers with bounded scheduling, add cooperative cancellation, and
   perform size checks before reading input. Preserve archive and memory limits.
4. Define stable diagnostic codes, severity, stage, source location, and user-facing
   remediation while preserving existing readable messages.
5. Add shared capacity-model golden vectors or one authoritative execution path.
   Distinguish heuristic estimates from calibrated and validated results.
6. Test standalone wheels, complete portal bundles, containers, and desktop bundles
   outside the source checkout. Document platform-specific limitations.

Exit gate: measured resource and latency results, reliable cancellation, cross-runtime
model parity for agreed inputs, and reproducible installed-distribution smoke tests.

## Phase 4: Extension proof and delivery

1. Exercise the contracts with a separately packaged SSIS intake and synthetic fixtures.
   Define supported export formats and operation coverage before implementation.
2. Exercise an independently packaged Databricks evaluate-only provider. Verify
   discovery, compatibility, neutral assessment, target evaluation, and capability gates.
3. Define Databricks output types, bindings, authentication, deployment provenance,
   and semantic parity criteria before adding compilation and UAT deployment.
4. Publish source-operation and target-capability matrices and update the
   [developer guide](../Guides/developer-contribution-guide.md),
   [plugin guide](../Guides/building-plugins.md), and business requirements.

Exit gate: both extension proofs work without adding source- or target-specific branches
to the run engine. Production support requires approved fixtures, independent parity
evidence, and QA-approved UAT.

## Validation and rollout

Add focused regression tests for each changed behavior, then run relevant local
end-to-end acceptance tests. Before committing, run the repository's Python lint,
type-check, and coverage gates and the web lint, test, and build gates. Do not dispatch
GitHub Actions or deploy workloads without explicit approval.

Deliver in small reviewable changes. Record intentional schema, rules-version, logical-ID,
and artifact-path migrations; keep old readers and rollback paths until consumers migrate.
