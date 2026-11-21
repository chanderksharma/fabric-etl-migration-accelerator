---
title: Pluggable Architecture Analysis and Target Approach
description: Current-state analysis and phased approach for source-neutral assessment and extensible target-platform migration
ms.date: 2026-11-20
ms.topic: concept
---

## Executive conclusion

The accelerator already contains a strong foundation for source-system
extensibility. Source adapters detect native exports and normalize them into a
canonical ETL intermediate representation.

The main architectural coupling occurs after normalization. Assessment,
generation, capacity planning, user experience, and deployment currently
assume Microsoft Fabric concepts. The target architecture must separate the
description of the source estate from the evaluation and implementation of a
selected destination platform.

The recommended model has two assessment stages:

1. Platform-neutral portfolio assessment establishes what exists in the source
   estate.
2. Target-platform fit assessment evaluates that estate against Microsoft
   Fabric, Databricks, or another registered platform.

This separation enables independent source modules, target evaluators,
generators, and deployment providers.

## Current-state strengths

The current implementation provides several reusable foundations:

* The source adapter contract defines stable detection and parsing operations.
* The source adapter registry provides deterministic adapter selection.
* Alteryx, Informatica PowerCenter, and Informatica IDMC are represented as
  source platforms.
* Native source assets normalize into a versioned canonical ETL package,
  asset, and graph representation.
* Unsupported constructs fail closed and produce diagnostics.
* Generated outputs retain deterministic version and source metadata.

These capabilities should be preserved and generalized rather than replaced.

## Current-state coupling

### Source registration

Supported source platforms are represented by a fixed enumeration, and the
default registry manually constructs the built-in adapters. Adding a source
therefore requires changes to central modules.

Alteryx also follows a legacy assessment and generation path while Informatica
assets use the newer canonical ETL pipeline. All source products should use one
normalization and orchestration path.

### Assessment

The current ETL assessment combines platform-neutral facts with Fabric target
recommendations. Support categories directly map operations to Dataflow,
Notebook, Pipeline, or manual implementation.

This makes the assessment result unsuitable as a durable source-neutral
business record. A change to Fabric compiler coverage can change the apparent
assessment of the source estate even though the source estate has not changed.

### Generation

Generation accepts a fixed set of Fabric implementation targets. Routing calls
the Fabric compilers to determine the recommended target and remaining effort.

The central generation path therefore owns both orchestration and
platform-specific implementation knowledge.

### Capacity planning

Capacity calculations use Fabric components and Fabric capacity units as
first-class concepts. Capacity planning should be supplied by target-platform
providers after target selection.

### Deployment

Deployment validation assumes Fabric workspaces and Fabric definitions. GitHub
and GitLab integrations dispatch Fabric-specific workflows and variables.

Target deployment and CI/CD transport should be composed rather than embedded
in the same service.

### User experience and API contracts

The assessment response exposes one recommended target and one collection of
target components. The user experience presents a recommended Fabric design
rather than a neutral assessment followed by target comparison.

The API and user experience must represent neutral assessment, target-fit
evaluations, platform selection, generation, and deployment as separate
business stages.

## Target component model

```text
Source ETL exports
        |
        v
Source Adapter Registry
  +-- Alteryx provider
  +-- PowerCenter provider
  +-- IDMC provider
  +-- Future source provider
        |
        v
Canonical ETL Intermediate Representation
        |
        +----------------> Portfolio Assessment Engine
        |                     +-- inventory
        |                     +-- complexity
        |                     +-- dependencies
        |                     +-- source risks
        |                     +-- migration-wave inputs
        |
        v
Target Platform Evaluation Registry
  +-- Microsoft Fabric evaluator
  +-- Databricks evaluator
  +-- Future platform evaluator
        |
        v
Target comparison and user selection
        |
        v
Code Generator Registry
  +-- Fabric generators
  +-- Databricks generators
  +-- Future platform generators
        |
        v
Generated Artifact Package
        |
        +-- Export for review
        |
        +-- Optional Deployment Registry
              +-- Fabric deployer
              +-- Databricks deployer
              +-- Future deployer
```

## Capability boundaries

### Source providers

Each source provider owns:

* Format detection
* Native export validation
* Secure parsing
* Source metadata extraction
* Canonical normalization
* Source-specific diagnostics
* Adapter, parser, and compatibility versions

Source providers must not contain target-platform mappings or deployment logic.

### Portfolio assessment engine

The portfolio assessment engine owns:

* Asset and workflow inventory
* Transformation and connector inventory
* Dependency analysis
* Graph complexity
* Scheduling and orchestration inventory
* Source quality and parsing findings
* Unknown and unsupported source constructs
* Portfolio segmentation and migration-wave inputs
* Evidence and traceability

The engine must not refer to Dataflow, Fabric Notebook, Fabric Pipeline,
Databricks Workflow, or another platform implementation component.

### Target-platform evaluators

Each target evaluator owns:

* Capability mapping against the canonical ETL representation
* Native implementation coverage
* Candidate target components
* Unsupported and partially supported constructs
* Manual redesign requirements
* Migration effort adjustments
* Platform-specific operational considerations
* Capacity and cost-planning inputs
* Generator and deployer availability

Target evaluators must not modify the neutral assessment. They produce separate
versioned evaluations that reference it.

### Code generators

Each generator owns:

* Supported canonical operations
* Target syntax
* Target artifact structure
* Required configuration and runtime bindings
* Target-specific diagnostics
* Static validation
* Artifact manifests and provenance

The central generation engine selects and invokes generators. It does not own
platform syntax.

### Artifact validators

Validation should remain distinct from generation. A target provider may
contribute:

* Schema validation
* Static syntax validation
* Dependency validation
* Environment readiness validation
* Semantic parity evidence requirements

Generated artifacts remain unvalidated for production until the required
independent checks are accepted.

### Deployment providers

Each deployment provider owns:

* Environment identity and configuration
* Deployment planning
* Dry-run validation
* Target API or command invocation
* Deployment polling when supported
* Readback and verification
* Deployment receipts and diagnostics

Deployment providers consume generated artifact packages. They must not parse
source ETL exports or regenerate code.

### Delivery-channel providers

Delivery-channel providers own dispatch to GitHub Actions, GitLab CI, Azure
DevOps, or another automation system.

A delivery channel transports an approved deployment request. It does not own
the target-platform deployment semantics.

## Recommended registries

Use independent registries for each extension dimension:

1. Source adapter registry.
2. Target evaluator registry.
3. Code generator registry.
4. Artifact validator registry.
5. Deployment provider registry.
6. Delivery-channel registry.

Registration metadata should include:

* Stable provider identifier
* Display name
* Provider version
* Supported contract versions
* Capabilities
* Supported canonical IR versions
* Configuration schema
* Availability and health

A provider may implement only a subset of capabilities. Databricks support, for
example, may begin with target-fit evaluation and add generation and deployment
in later releases.

## Platform provider composition

A target platform should be distributed as a capability bundle rather than a
single large implementation.

```text
Microsoft Fabric platform provider
  +-- fit evaluator
  +-- capacity estimator
  +-- Dataflow Gen2 generator
  +-- Fabric Notebook generator
  +-- Data Pipeline generator
  +-- artifact validator
  +-- deployment provider

Databricks platform provider
  +-- fit evaluator
  +-- capacity estimator
  +-- PySpark generator
  +-- Workflow generator
  +-- Lakeflow or DLT generator
  +-- Asset Bundle packager
  +-- artifact validator
  +-- deployment provider
```

The central system discovers the available capabilities and exposes only the
operations supported by the installed providers.

## Core data contracts

### Portfolio assessment

The neutral portfolio assessment should contain:

* Assessment identity and version
* Canonical IR version
* Source-provider versions
* Asset inventory
* Graph and dependency evidence
* Complexity indicators
* Source findings
* Unknown constructs
* Data endpoints
* Scheduling metadata
* Assessment confidence and limitations

### Target-fit assessment

One target-fit assessment should be produced for each evaluated platform:

* Target platform identifier
* Evaluator version
* Referenced portfolio assessment identity
* Compatibility and native coverage
* Candidate components
* Unsupported constructs
* Required manual redesign
* Estimated effort
* Capacity and operational inputs
* Recommendation rationale
* Available generation and deployment capabilities

### Platform selection

The user decision should be recorded separately:

* Selected platform
* Selected target components
* Referenced target-fit assessment
* Approved assumptions
* Required bindings
* Decision timestamp and actor

### Generation result

The generation result should contain:

* Generator identity and version
* Referenced platform selection
* Generated artifacts
* Artifact hashes
* Diagnostics
* Required bindings
* Validation state
* Source-to-target traceability

### Deployment plan and receipt

The deployment plan should contain environment-specific operations, blockers,
warnings, and required approvals.

The deployment receipt should contain deployment identity, target environment,
status, deployed resources, verification evidence, and failure diagnostics.

## Product workflow

Expose four independently usable product capabilities:

1. Assess portfolio.
2. Compare target platforms.
3. Generate migration artifacts.
4. Deploy generated artifacts.

The expected user journey is:

1. Select an ETL estate.
2. Run source discovery and normalization.
3. Review the platform-neutral portfolio assessment.
4. Evaluate one or more target platforms.
5. Compare coverage, effort, risk, and operational considerations.
6. Select a target platform and approve assumptions.
7. Generate platform-specific artifacts.
8. Review validation evidence and required bindings.
9. Download the artifacts or select an optional deployment provider.
10. Validate deployment readback and semantic parity.

Users can stop after any stage and retain that stage's output.

## Recommended implementation approach

Start with a modular monolith. Establish stable contracts and dependency
direction before considering separate services.

### Phase 1: Unify source processing

* Route Alteryx through the canonical ETL representation.
* Remove source-specific branching from central assessment and generation
  orchestration.
* Make the canonical representation the only accepted downstream input.
* Preserve current deterministic parsing and fail-closed behavior.

### Phase 2: Separate neutral and target assessment

* Remove Fabric component recommendations from the portfolio assessment.
* Introduce target-fit assessment as a separate output.
* Move platform capacity planning behind target-platform capabilities.
* Preserve current assessment fields through an explicit compatibility layer
  while consumers transition.

### Phase 3: Extract the Fabric provider

* Move Fabric routing rules behind the target evaluator contract.
* Move Fabric generators behind generator contracts.
* Move Fabric artifact validation behind validator contracts.
* Move workspace deployment behavior behind the Fabric deployment provider.
* Preserve current Fabric behavior and artifact formats.

### Phase 4: Introduce target comparison

* Add a target-platform catalog.
* Evaluate the same neutral assessment against all selected targets.
* Present comparable coverage, gaps, effort, and capability availability.
* Record the user's platform selection separately from assessment.

### Phase 5: Add Databricks capabilities

* Implement the Databricks fit evaluator first.
* Agree canonical-operation mappings and unsupported behavior.
* Add generators in bounded increments.
* Add Databricks artifact validation.
* Add deployment only after generated artifacts and validation contracts are
  stable.

### Phase 6: Enable external plug-ins

* Replace fixed source and target enumerations with stable identifiers where
  persisted compatibility allows.
* Add manifest-based or package-entry-point discovery.
* Validate provider identity, capability, and contract versions during startup.
* Isolate provider failures and report unavailable capabilities explicitly.
* Define supported installation, upgrade, and removal behavior.

## Compatibility strategy

The transition must preserve current Fabric behavior while contracts evolve.

Recommended compatibility controls:

* Version neutral assessment, target-fit, generation, and deployment contracts
  independently.
* Store provider identifiers and versions with every output.
* Retain adapters for current API responses during a defined migration period.
* Reject incompatible provider and canonical IR versions explicitly.
* Avoid silent fallbacks when a requested capability is unavailable.
* Keep generated artifacts byte-stable when inputs and provider versions are
  unchanged.

## Quality and governance requirements

The pluggable architecture must preserve these invariants:

* Source content is treated as untrusted and is never executed during parsing.
* Credentials and customer-sensitive data are excluded from canonical outputs.
* Core processing remains deterministic and does not depend on AI inference.
* Unsupported transformations produce explicit scaffold diagnostics.
* Runnable-looking deployment envelopes are produced only for supported,
  validated artifact structures.
* Provider failures are isolated and do not corrupt assessment state.
* Every assessment, generation, and deployment result retains provenance.
* Extension behavior is covered by provider contract tests.

## Acceptance criteria

The target architecture is successful when:

* A new ETL source can be added without modifying the assessment engine.
* A new target platform can be added without modifying source adapters.
* All source platforms use the same canonical downstream pipeline.
* Neutral assessment runs without a target selection.
* Multiple target evaluators can process one neutral assessment.
* Target selection is recorded independently from the assessment.
* Generation requires an explicit target selection.
* The central generation engine contains no platform syntax.
* Deployment remains optional.
* Target deployment and CI/CD dispatch are independently selectable.
* A provider can support assessment before supporting generation or
  deployment.
* Existing Fabric behavior remains available through the Fabric provider.
* Unsupported constructs continue to fail closed with actionable diagnostics.

## Recommended architectural principle

Sources describe the estate. The portfolio assessment describes the work.
Target evaluators describe platform fit. Generators create artifacts. Deployers
deliver approved artifacts.

Each capability depends on versioned contracts, not on product-specific
branching in the central engines.

