---
title: Pluggable Architecture Delivery Team Draft
description: Delivery brief for evolving the existing accelerator into a pluggable multi-source and multi-target migration platform
ms.date: 2026-11-20
ms.topic: concept
---

## Status

Draft for delivery-team review and estimation.

## Delivery objective

Evolve the existing Microsoft Fabric ETL Migration Accelerator into a
pluggable migration platform that supports:

* Multiple source ETL products through independently registered source modules
* Platform-neutral portfolio assessment
* Target-platform comparison and selection
* Independent code generation for Microsoft Fabric, Databricks, and future
  platforms
* Optional target-specific deployment
* Independent CI/CD delivery channels

The existing repository is the implementation base. The work is an incremental
refactor and extension, not a greenfield rebuild.

## Existing capabilities to reuse

The delivery estimate assumes continued use of:

* Existing Alteryx, Informatica PowerCenter, and Informatica IDMC adapters
* Source adapter detection and registration
* Canonical ETL intermediate representation
* Deterministic assessment and routing logic
* Fabric Dataflow Gen2 generation
* Fabric Notebook generation
* Fabric Data Pipeline generation
* GitHub Actions and GitLab CI dispatch foundations
* FastAPI service and Typer CLI
* React portfolio user experience
* SQLite run state and immutable snapshots
* Existing security, deterministic-processing, and fail-closed controls
* Existing automated test and synthetic-fixture foundation

Existing behavior should be extracted behind stable provider contracts rather
than rewritten.

## Target business flow

```text
Source ETL exports
    |
    v
Source adapter modules
    |
    v
Canonical ETL representation
    |
    v
Platform-neutral portfolio assessment
    |
    v
Target-platform evaluation and comparison
    |
    v
User selects Microsoft Fabric, Databricks, or another platform
    |
    v
Selected platform generators
    |
    v
Generated migration artifact package
    |
    +-- Download and review
    |
    +-- Optional target-platform deployment
```

## Required architecture boundaries

### Source providers

Source providers detect and parse native exports, then normalize assets into
the canonical ETL representation.

Adding a source provider must not require changes to portfolio assessment,
target evaluation, code generation, or deployment engines.

### Portfolio assessment

Portfolio assessment describes the source estate:

* Assets and workflow inventory
* Components and transformations
* Dependencies and orchestration
* Data sources and destinations
* Complexity indicators
* Unknown and unsupported source constructs
* Evidence and traceability
* Migration-wave inputs

The neutral assessment must not recommend Fabric or Databricks components.

### Target-platform evaluators

Each target evaluator determines:

* Native implementation coverage
* Candidate target components
* Unsupported constructs
* Manual redesign requirements
* Estimated migration effort
* Capacity and operational considerations
* Available generation and deployment capabilities

Multiple target evaluators must be able to process the same neutral assessment.

### Code generators

The central generation engine selects registered generators. Platform-specific
providers own their syntax, artifact formats, validation rules, and required
runtime bindings.

### Deployment providers

Deployment remains optional. Target deployers own platform APIs, environment
validation, dry runs, deployment execution, readback, and verification.

GitHub Actions, GitLab CI, Azure DevOps, and other delivery channels remain
separate from target-platform deployment semantics.

## Delivery scope

### Shared pluggable foundation

* Route all current source tools through one canonical downstream path
* Separate neutral assessment from target-fit assessment
* Introduce versioned provider contracts and independent registries
* Add provider discovery, compatibility validation, and lifecycle handling
* Update API and UI contracts for target comparison and explicit selection
* Preserve deterministic output and source-to-target provenance

### Microsoft Fabric provider

* Extract current Fabric routing into a Fabric target evaluator
* Extract Dataflow, Notebook, and Pipeline generators
* Move Fabric capacity planning behind the provider boundary
* Extract Fabric artifact validation
* Extract Fabric workspace deployment behavior
* Preserve current Fabric artifact formats and supported behavior

### Databricks provider

* Implement target-fit evaluation
* Implement bounded PySpark and notebook generation
* Implement Databricks Workflow generation
* Package artifacts through Databricks Asset Bundles where applicable
* Add target-specific validation and required-binding diagnostics
* Add workspace deployment, readback, and deployment evidence

### Cross-platform integration

* Present comparable Fabric and Databricks evaluations
* Record platform selection separately from assessment
* Generate only for an explicitly selected platform
* Keep export-only use available without deployment
* Add provider contract, compatibility, regression, and end-to-end tests

## High-level effort

The estimate assumes that the delivery team uses GitHub Copilot for
implementation, refactoring, tests, documentation, and repetitive provider
patterns. Architecture, semantic mapping, security, and platform validation
remain human-reviewed.

| Workstream | Estimated effort |
| --- | ---: |
| Shared provider contracts and neutral assessment | 6-8 person-weeks |
| Microsoft Fabric provider extraction and hardening | 3-4 person-weeks |
| Databricks evaluator, generators, and deployment provider | 6-8 person-weeks |
| Cross-platform integration, compatibility, and validation | 3-4 person-weeks |
| Total delivery estimate | 18-24 person-weeks |

The estimate includes the shared foundation once and assumes that independent
workstreams proceed in parallel.

## Indicative schedule

| Delivery team | Estimated duration |
| --- | ---: |
| Two developers | 9-12 weeks |
| Three developers with part-time QA and architecture support | 7-9 weeks |
| Four-person cross-functional team | 6-8 weeks |

Recommended planning baseline:

* Three developers
* Part-time platform architect
* Part-time quality engineer
* Part-time security reviewer
* Eight calendar weeks for implementation
* Up to two additional weeks for platform validation and release acceptance

## Indicative delivery sequence

### Iteration 1: Provider foundation

Duration: 2-3 weeks.

* Define versioned provider contracts and capability metadata
* Unify current sources on the canonical ETL pipeline
* Separate neutral assessment from target evaluation
* Introduce provider registries and compatibility checks

### Iteration 2: Fabric extraction

Duration: 1-2 weeks.

* Move Fabric evaluation, generation, capacity, validation, and deployment
  behind provider boundaries
* Preserve current Fabric outputs and regression behavior

### Iteration 3: Databricks provider

Duration: 2-3 weeks.

* Add Databricks fit assessment
* Add bounded generation and artifact packaging
* Add deployment planning, execution, and readback

### Iteration 4: Plug-in lifecycle and integration

Duration: 1-2 weeks.

* Add package or manifest discovery
* Validate provider and contract compatibility
* Expose target comparison and platform selection
* Isolate provider failures

### Iteration 5: Release validation

Duration: 1-2 weeks.

* Complete contract and end-to-end tests
* Validate deterministic generation
* Confirm deployment dry runs and readback
* Complete security and operational review

Iterations overlap after the provider contracts stabilize.

## Key assumptions

* The existing repository remains the product and implementation base
* The canonical ETL representation is extended only where required
* Existing Fabric behavior is preserved and extracted, not rewritten
* Databricks support covers an agreed deterministic operation subset
* External plug-ins run as trusted installed packages or manifest-discovered
  components
* Remote or untrusted plug-in execution is not included
* Existing FastAPI, React, CLI, SQLite, and CI/CD foundations remain
* GitHub Copilot-generated changes receive normal human review
* Delivery uses synthetic fixtures and does not introduce customer data
* Production semantic parity remains an explicit validation gate

## Out of scope for the initial delivery

* Complete translation of every transformation supported by every ETL product
* Automatic execution of source expressions during assessment
* Unreviewed production deployment
* Remote plug-in marketplace or arbitrary remote plug-in execution
* AI-based source parsing or non-deterministic generation
* Automatic semantic-parity certification
* Complete cost optimization for every Fabric or Databricks workload type

## Delivery risks

| Risk | Mitigation |
| --- | --- |
| Canonical representation lacks semantics required by Databricks generators | Extend the representation through versioned, source-neutral fields and contract tests. |
| Fabric behavior changes during provider extraction | Preserve existing artifact fixtures and regression tests before moving logic. |
| Provider contracts become platform-specific | Review contracts against both Fabric and Databricks before implementation. |
| Plug-in failures affect central processing | Isolate provider execution and return explicit capability failures. |
| Generated artifacts appear production-ready without parity evidence | Preserve unvalidated states, required bindings, and fail-closed diagnostics. |
| Deployment scope expands into CI/CD redesign | Keep delivery channels separate from target deployment providers. |

Retain a 10-15 percent contingency for canonical-model changes,
source-to-target semantic gaps, deployment authentication, and
platform-specific validation.

## Acceptance criteria

Delivery is complete when:

* A new source adapter can be installed without changing assessment or
  generation engines.
* A new target platform can be installed without changing source adapters.
* All current source platforms use the canonical downstream pipeline.
* Portfolio assessment runs without a selected target platform.
* Fabric and Databricks can evaluate the same assessment.
* Platform selection is recorded independently.
* Generation requires explicit platform selection.
* The central generation engine contains no target-platform syntax.
* Fabric functionality remains compatible with current supported behavior.
* Databricks produces bounded, deterministic artifacts and explicit
  diagnostics.
* Deployment remains optional.
* Target deployers and CI/CD delivery channels are independently selectable.
* Provider and canonical contract incompatibilities fail explicitly.
* Automated contract, regression, and end-to-end tests pass.

## Delivery-team review decisions

The delivery team should confirm:

1. The initial Databricks operation and artifact scope.
2. The external plug-in packaging and discovery mechanism.
3. The canonical ETL representation changes required by both target providers.
4. The compatibility period for current assessment API fields.
5. The deployment environments included in the initial release.
6. The semantic-parity evidence required before deployment approval.
7. Team allocation and iteration ownership.

## Supporting requirements

* [Pluggable Architecture Business Requirements](./pluggable-architecture-business-requirements.md)
* [Pluggable Architecture Analysis and Target Approach](./pluggable-architecture-analysis-and-approach.md)

