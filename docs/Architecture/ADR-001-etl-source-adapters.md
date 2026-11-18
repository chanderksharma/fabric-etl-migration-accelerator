# ADR-001: Source Adapters and Canonical ETL IR

## Status

Proposed. Governed alternate-model review remains required before this
architecture advances beyond the compatibility baseline.

## Context

The current accelerator directly couples secure discovery, graph parsing,
assessment, evidence, and Fabric generation to Alteryx workflow formats and
plugin identities.

ETL Fabric Accelerator must also support Informatica PowerCenter repository
exports and IICS/IDMC export packages. PowerCenter and IDMC represent mappings,
orchestration, dependencies, parameters, connections, and schedules
differently. Adding product checks to the Alteryx parser would create an
unmaintainable shared implementation and increase regression risk.

Existing Alteryx APIs, CLI commands, artifact paths, generated filenames, and
user behavior must remain compatible.

## Decision

Introduce source adapters and a versioned canonical ETL intermediate
representation (IR).

Each source adapter owns:

- Native format and package detection.
- Secure parsing.
- Product and asset version detection.
- Conversion to the canonical ETL IR.
- Platform-specific support registries.
- Platform-specific evidence enrichments.
- Transformation and orchestration translation metadata.

Shared services consume the IR for:

- Assessment and complexity scoring.
- Fabric target routing.
- Evidence and portfolio registers.
- Dataflow Gen2 generation.
- Fabric Notebook generation.
- Fabric Data Pipeline generation.
- Artifact packaging and deployment planning.

The IR keeps mapping and orchestration graphs separate while preserving stable
native identifiers and source locations.

## Cross-source generation requirements

- Apply the same target-routing order to Alteryx and Informatica: Dataflow
  first, then Notebook, then multi-item Pipeline orchestration.
- Generate Dataflow for a complete mapping only when every operation has a
  deterministic Dataflow implementation.
- Generate a deployable Notebook for a single-mapping Informatica workflow
  when Dataflow is incomplete. Source-specific operations must appear as named
  `transform_bindings`, never silent pass-through behavior.
- Mark generated definitions runtime-not-ready while source, destination,
  transformation, or semantic-parity bindings remain unresolved.
- Generate a Fabric Data Pipeline only when multiple Fabric items require
  dependency orchestration. Do not wrap one Dataflow or Notebook in a redundant
  Pipeline.
- Reserve Manual rework for graph shapes that cannot yet be emitted without
  losing orchestration semantics (such as unsupported control/command tasks or
  cyclic graphs). Multi-mapping PowerCenter workflows with supported session and
  assignment orchestration compile to Notebook/Dataflow compute plus a Fabric
  Data Pipeline bundle.
- Report unresolved stages individually so a supported mapping does not make
  the entire source estate appear unsupported.

Compatibility wrappers retain current Alteryx imports and functions during the
migration. Existing Alteryx artifact paths remain unchanged. Informatica
artifacts use explicit platform roots below `generated-fabric-workflows`.

## Consequences

### Positive

- Source products evolve independently.
- Fabric emitters and portfolio logic are reusable.
- Unsupported semantics remain explicit per adapter.
- Cache and artifact versioning can include adapter versions.
- Existing Alteryx behavior can be protected with executable contracts.

### Negative

- The refactor introduces an additional model-conversion layer.
- IR evolution requires explicit versioning and migration policy.
- Source-specific detail must be preserved without leaking native raw payloads
  into shared compiler logic.
- PowerCenter and IDMC fixtures are required before translator coverage can be
  considered reliable.

## Alternatives considered

### Extend current Alteryx modules with Informatica branches

Rejected because parsing rules, native identities, package structure, and
orchestration semantics differ substantially across products.

### Maintain three independent end-to-end implementations

Rejected because assessment, Fabric definition serialization, packaging,
deployment, and portfolio behavior would drift.

### Normalize only at the UI/API boundary

Rejected because compiler and evidence reuse requires a source-neutral model
before assessment and generation.

## Compatibility requirements

- Preserve all current Alteryx input extensions.
- Preserve existing API routes and CLI commands.
- Preserve `generated-fabric-workflows` as the artifact root.
- Preserve current Alteryx relative artifact paths.
- Evolve schemas additively with Alteryx-compatible defaults.
- Fail incompatible cached runs explicitly rather than silently reinterpreting
  them.

## Validation

- Existing Alteryx tests remain green.
- Compatibility contract tests cover routes, CLI commands, schema fields,
  extensions, and artifact paths.
- Alteryx golden artifacts are byte-equivalent or explicitly allow-listed.
- Every source adapter has parser, IR, assessment, evidence, and compiler
  goldens before release.

