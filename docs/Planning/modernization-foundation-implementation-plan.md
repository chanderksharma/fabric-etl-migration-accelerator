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
size before reading its bounded identification header. Artifact writing parses each
workflow once and compiles each needed target once per write; previews and single-target
packages skip the cross-target deployment plan they never read.
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
remain readable and are reassessed when these versions change. Parsed canonical
`EtlPackage` IR and neutral assessments are also cached in SQLite (`ir_cache` and
`cache`). Cold Alteryx assessment parses each workflow once: the same parse feeds the
Fabric engines and seeds `ir_cache`, so the neutral baseline and later evaluations read
the cache, and a warm run parses nothing. Generation parses each workflow once per
write, whatever the number of targets. Source
adapters may implement `SourceStreamProbeAdapter` (`probe_bytes`) to probe
archive entries in memory without staging temporary directories, and `DiscoveryService`
shares ZIP validation with `IdmcSourceAdapter`. `etl-migration-core` now provides
canonical operation categories (`contracts/operations.py`), structured `Diagnostic`
models, SemVer IR compatibility checks (`is_ir_compatible`), typed optional SPI
capability protocols (`TargetCodeGeneratorProvider`, `TargetCapacityProvider`),
`TargetPlatformInfo.target_kinds` (validated against the code generator), and reusable
conformance helpers
(`contracts/testing.py`). The unimplemented deployment planner protocols and the
`DeliveryChannel` protocol were removed because nothing implemented or called them.
`FabricTargetProvider` implements `code_generator()` and
`capacity_estimator()`. The local API exposes `GET /api/sources`, `GET /api/plugins`,
lightweight
`GET /api/runs/{run_id}/status`, and capability-routed target generation and capacity
endpoints (`/api/runs/{run_id}/targets/{platform_id}/generate` and `/capacity`), and
`artifact_writer` supports an opt-in `identity_mode="asset"` with
`build_logical_id_migration_plan()` while preserving existing content-based logical
IDs by default. Full Alteryx migration off `WorkflowGraph`, multi-target CI dispatch
channels, and production SSIS/Databricks semantics remain open. The main CLI exposes `assess-neutral` alongside the existing
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

## Review follow-up: reliability, performance, and plugin operations

A second architecture review measured the foundation and drove these changes. They
are implemented but uncommitted pending review, and none was exercised in real CI or
Fabric deployments.

**Reliability.** An unexpected exception from one plugin or engine now fails that one
workflow instead of leaving the run stuck in `running`: adapter `probe`/`parse` faults
become `SourceAdapterFaultError`, target provider faults become
`TargetProviderFaultError`, and the worker loop logs and continues. A run interrupted
five times is quarantined as `failed`. A plugin that fails to import is recorded in
`plugin_results`, `GET /api/plugins`, and `tool plugins` while built-in adapters keep
working; `ACCELERATOR_PLUGIN_ALLOWLIST` limits which entry points load. One invalid
target provider no longer hides the catalog (`faults` list). Discovery builds candidate
metadata from the adapters in one place, so built-in sources produce identical
snapshots with or without an injected registry.

**Correctness of derived data.** The SQLite store uses ordered, idempotent schema
migrations and honors its 30 second busy timeout. That review reached schema 6.
The suggested-order follow-up appends schema 7 without editing the schema-4 baseline. Neutral rules carry a
content fingerprint in their version, Fabric support tables carry one in the Fabric
cache key, and contract tests keep the neutral and Fabric operation tables consistent
(annotation tools such as containers are now neutral in both). A reviewed list records
the operations Fabric cannot compile (`merge`, `rtool`).

**Performance** (15 sample workflows, 261 KiB, one Windows machine; ratios transfer
better than milliseconds):

| Operation | Before | After |
| --- | --- | --- |
| Cold assessment run | 1,095 ms, 30 parses | about 130 ms, 15 parses |
| Warm assessment run | 190 ms | about 11 ms, 0 parses |
| One-target preview | 1,594 ms, 45 parses | about 240 ms, 15 parses |
| Three-target publication | 4,088 ms, 45 parses | about 1,300 ms, 15 parses |

The causes were a 100 MiB preallocation on every file read, one SQLite connection per
statement, a second parse for the canonical IR, and compiling every target for a
single-target preview. The portal now polls `GET /api/runs/{id}/status` and loads the
full result once.

**Operations.** `ACCELERATOR_STATE_DIR`, `ACCELERATOR_ARTIFACT_DIR`,
`ACCELERATOR_PLUGIN_ALLOWLIST`, and `ACCELERATOR_LOG_LEVEL` configure the CLI and API
identically; runs persist stage timings; `tool gc` bounds local state growth.

**Build and CI.** The `security-audit` job ran `uvx pip-audit --strict`, which audits
only pip-audit's own tool environment (29 packages) and never the project. It now
exports the locked dependency set (94 hashed pins, all extras) and audits that. The first
honest run found `pytest 8.4.2` (PYSEC-2026-1845) and `tornado 6.6` (CVE-2026-126347),
both development-only; the lock now carries `tornado 6.6.1` and `pytest>=9.0.3,<10`
(locked at 9.2.0), and the full suite passes on those versions. The same workflow also
runs on a weekly schedule and on demand, where only the security jobs run; the schedule
takes effect once the workflow is on the default branch. A new `plugin-entry-points` job
installs both example plugins as real distributions and runs `tests/test_installed_plugins.py`
and `tool plugins`, so the entry-point path is exercised outside the unit tests; the test
skips locally and fails when `ACCELERATOR_REQUIRE_INSTALLED_PLUGINS=1` and the plugins are
missing. Ruff also enforces `ASYNC`, `BLE`, `DTZ`, `ERA`, `G`, `LOG`, `PLE`, `PTH`, `RET`
and the eval, exec, pickle, YAML, and shell subset of `S`; every broad `except Exception`
carries a reason. Ruff and mypy cover the example plugins. The deployment workflows read
`vars.DEPLOY_RUNNER_LABELS` (same default as before) instead of hard-coded labels, and
`tests/conftest.py` clears the `ACCELERATOR_*` settings so a developer's shell cannot
redirect test state.

**Python floor.** The suite was run on Python 3.12.10 without installing the packages:
401 of the 402 tests that run pass. The one failure executes a generated Fabric notebook whose runtime
guard requires Python 3.13 by design. The floor stays `>=3.13`: `tests/test_project_configuration.py`
pins it, and lowering the neutral libraries to 3.12 trades Fabric Runtime 2.0 parity for
developer-workstation portability, which is a product decision. If taken, it also needs a
CI matrix and a change to that test.

**Defects found by the final review.** An independent read-only review of the whole diff
found three defects, all reproduced with a failing test before the fix. (1) Existing
state directories could not be opened: the schema-4 baseline had been edited to include
the new `ir_cache` table, so a database written by the last release (schema 4, no such
table) failed in the next step with `no such table`. My migration test missed it because
it built its "old" database with the code under test. The baseline is back to exactly the
released schema, `ir_cache` is created by the next step, the test now uses a literal copy
of the released DDL and compares the migrated schema with a fresh one, and state created
by the released code was opened with the new code (migrated 4 to 6, the old run still
readable, a re-run and a publication succeeded). (2) `ACCELERATOR_PLUGIN_ALLOWLIST` was
applied only on some paths; the library facades, the stateless CLIs, and a plain
`RunService()` still imported every installed plugin. The default registry factories now
resolve the allowlist themselves, so no application path imports an entry point that is
not approved. (3) One plugin with an invalid `supported_extensions` entry stopped the portal
from starting, because discovery validated every extension at construction. Probing for
the same class of defect found a fourth: a plugin with a non-string `adapter_version` was
registered as `loaded`, then crashed the plugin catalog (`GET /api/plugins`, `tool
plugins`), the very tools meant to diagnose it. Extension and identity/version metadata
are now validated at registration, so such a plugin is reported as `failed` and the
built-in sources and the catalog keep working.

**Structure.** `RunService` delegates storage to `runtime/store.py`, identities and cache
keys to `runtime/identity.py`, publications to `runtime/publication.py`, and models to
`runtime/models.py`; the API moved upload staging, schemas, and deployment resolution
into their own modules; `PluginHost` gives the API and CLI one typed plugin catalog.

**Suggested-order follow-up.** The third review's order is applied as a refactor, not a
compiler rewrite. Missing linear Alteryx configuration keys now scaffold, and an unexpected
generation fault becomes a blocked candidate so one bad workflow does not drop the estate;
`OSError` and `sqlite3.Error` still fail the write. Power Query literals share
`m_literals.m_string`, and malformed M is not marked `generated_unvalidated`. Remaining
effort uses one integer half-even helper in `etl_migration_core.planning`. Folder upload
raises only the named-file cap, to 10,000. `tests/test_golden_digest.py` hashes a fresh
write of `alteryx-workflows` plus `tests/fixtures/powercenter` (17 workflows, three
targets) after masking the run id and host path separators. That digest does not replace
`generated-fabric-workflows/`, which acceptance tests still read. Generation jobs and a
content-addressed candidate cache are additive; synchronous generate and preview stay
synchronous. `ArtifactSet` is a target-neutral projection and is not added to the Fabric
artifact tree. Schema 7 adds `generation_jobs`; the schema-4 baseline is unchanged.
Uvicorn is imported only when serving, and a missing `spi_version` remains `1.0.0`.
A local portal check on 2026-11-22 passed health, a 15-workflow assessment,
synchronous generate, a notebook generation job, publication download, and
malformed-workflow isolation. GitHub Actions and a live Fabric deployment were
not run. The operator and developer guides now describe the job routes, the
cache, `ArtifactSet`, and the SPI handshake. See
[System Architecture](../Architecture/system-architecture.md#local-generation-runtime).

**Still open.** Splitting `RunService` into collaborator objects is deliberately
deferred: many tests and the portal depend on its internal hooks, so it needs
characterization tests first. A wholesale compiler split into handlers and emitters is
also deferred; the golden digest is the safety net for that later change, not a claim
that it is done. `tests/test_delivery.py` (about 2,400 lines) should be split
by area; new tests already go in focused modules. Operation traits were not introduced because Fabric's
compiler coverage is narrower than the neutral categories, so deriving Fabric support
from them would over-claim. Process-pool parallelism, an out-of-process plugin protocol,
a content-addressed stage store, an OpenAPI-generated web client, authenticated server
mode, and a new database depend on measurement or a product decision about shared
deployment. The logical-ID migration is not wired into the runtime, and real CI and Fabric
deployments remain untested. The GitLab deployment job keeps its fixed runner tag, and
the Fabric compiler re-parses already-defused node configuration fragments with the
standard-library XML parser (22 sites), which is not exploitable today but is worth
moving to `defusedxml` as defense in depth.
