---
title: Pluggable Architecture Business Requirements
description: Business requirements for modular ETL portfolio assessment, target-platform code generation, and optional deployment
ms.date: 2026-11-20
ms.topic: concept
---

## Business objective

Evolve the accelerator into a pluggable ETL migration solution. New source ETL
tools and target data platforms must integrate through stable extension
contracts without requiring substantial changes to the central engines.

The solution must separate portfolio assessment, target-platform evaluation,
code generation, and deployment so that each capability can operate and evolve
independently.

## Core capabilities

### Portfolio assessment

The portfolio assessment capability must:

* Assess estates containing workflows from multiple ETL products
* Use source-specific modules to detect, parse, and normalize source assets
* Produce a common, source-neutral portfolio representation
* Apply consistent inventory, dependency, complexity, and risk analysis
* Operate without requiring a target platform selection
* Remain usable when code generation and deployment are not required

Adding another ETL product, such as a future orchestration or integration tool,
must require a new source module and its mappings. It must not require changes
to the central portfolio assessment engine.

### Target-platform evaluation

After the platform-neutral assessment, users must be able to evaluate and
select a target platform such as Microsoft Fabric or Databricks.

Each target-platform module must evaluate:

* Native mapping coverage
* Required target components
* Unsupported source constructs
* Manual redesign requirements
* Estimated migration effort
* Operational and capacity considerations
* Generator and deployment capability availability

The solution should support comparison across multiple target platforms before
the user makes a selection.

### Code generation

The code generation capability must:

* Remain separate from portfolio assessment
* Consume the canonical ETL representation rather than native source files
* Generate artifacts only for the selected target platform
* Delegate platform syntax and packaging to platform-specific generators
* Support additional target platforms without changing the central generation
  engine
* Emit explicit diagnostics when a safe translation is unavailable
* Preserve source-to-target traceability in every generated artifact

Platform differences must remain inside target-specific generators. The
central generation engine should orchestrate generators but should not contain
Fabric, Databricks, or other platform syntax.

### Deployment

The deployment capability must:

* Remain optional and independent from assessment and generation
* Support downloading generated artifacts without deploying them
* Provide dry-run validation before any deployment
* Delegate environment and API behavior to target-specific deployment modules
* Support multiple delivery channels, including GitHub Actions, GitLab CI, and
  future CI/CD integrations
* Return deployment status, diagnostics, and verification evidence

Target-platform deployment and CI/CD delivery are separate extension
dimensions. A Fabric or Databricks deployer must not be coupled directly to one
source-control or pipeline provider.

## Intended business flow

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
Target-platform comparison and selection
    |
    v
Selected platform code generator
    |
    v
Generated migration artifacts
    |
    +-- Download and review
    |
    +-- Optional target-platform deployment
```

## Architectural requirements

| ID | Requirement |
| --- | --- |
| BR-001 | New source ETL tools must integrate through independently registered source modules. |
| BR-002 | All source modules must normalize assets into a shared canonical ETL representation. |
| BR-003 | Portfolio assessment must remain independent of target-platform selection. |
| BR-004 | Target-platform fit must be evaluated after the platform-neutral assessment. |
| BR-005 | Multiple target platforms must be able to evaluate the same assessment result. |
| BR-006 | Code generation must be independent of source-tool parsing and assessment logic. |
| BR-007 | Each target platform must own its generators, artifact formats, and validation rules. |
| BR-008 | Deployment must be optional and independently selectable. |
| BR-009 | Target deployment providers and CI/CD delivery providers must remain separate. |
| BR-010 | Unsupported constructs must produce explicit diagnostics and must not produce misleading deployable artifacts. |
| BR-011 | Plug-in contracts and persisted outputs must be independently versioned. |
| BR-012 | Existing capabilities must continue to work when new source or target modules are installed. |

## Modularity expectations

The business capabilities should be available separately:

1. Assess a portfolio.
2. Compare target platforms.
3. Generate artifacts for a selected platform.
4. Deploy generated artifacts through an optional provider.

Users must be able to stop after any stage and retain the outputs produced by
that stage.

## High-level development effort

The estimate assumes that the development team uses GitHub Copilot for
implementation, refactoring, tests, documentation, and repetitive provider
patterns. Architecture decisions, semantic mappings, security review, and
platform validation remain expert-led activities.

A person-week represents one engineer working for one week.

| Workstream | Estimated effort |
| --- | ---: |
| Shared provider contracts and neutral assessment | 6-8 person-weeks |
| Microsoft Fabric provider extraction and hardening | 3-4 person-weeks |
| Databricks evaluator, generators, and deployment provider | 6-8 person-weeks |
| Cross-platform integration, compatibility, and validation | 3-4 person-weeks |
| End-to-end support for both target platforms | 18-24 person-weeks |

The combined estimate treats the work as an incremental extension of the
existing source adapters, canonical ETL representation, Fabric compilers, and
deployment foundations. It includes the shared foundation once and assumes
that independent workstreams proceed in parallel.

### Expected calendar duration

| Delivery team | Estimated duration |
| --- | ---: |
| Two developers | 9-12 weeks |
| Three developers with part-time QA and architecture support | 7-9 weeks |
| Four-person cross-functional team | 6-8 weeks |

The recommended planning baseline is 8 calendar weeks with three developers
and part-time support from platform architecture, quality engineering, and
security specialists. Retain up to 2 additional weeks for platform validation
and release acceptance.

### Delivery sequence

1. Establish shared provider contracts and platform-neutral assessment in 2-3
   weeks.
2. Extract and validate the Microsoft Fabric provider in 1-2 weeks.
3. Implement Databricks assessment, generation, and deployment capabilities in
   2-3 weeks.
4. Add external plug-in discovery, compatibility controls, and lifecycle
   handling in 1-2 weeks.
5. Complete cross-platform integration and release validation in 1-2 weeks.

These workstreams overlap after the provider contracts stabilize.

### Estimation assumptions

The estimate assumes:

* A modular monolith rather than an immediate microservices decomposition
* Preservation of the current deterministic and fail-closed behavior
* Reuse of the existing canonical ETL representation
* Incremental Fabric extraction rather than a complete rewrite
* Bounded Databricks support for agreed canonical operations
* Existing application entry points and user experience remain in place
* GitHub Copilot-generated changes receive human review
* Automated provider contract and regression testing is included
* External plug-ins use package or manifest discovery rather than remote
  plug-in execution
* Existing Fabric behavior is extracted and preserved rather than rewritten

Retain a 10-15 percent contingency for canonical-model changes,
source-to-target semantic gaps, deployment authentication, and
platform-specific validation.

## Extensibility outcome

The architecture is considered pluggable when:

* A source ETL tool can be added without modifying assessment or generation
  engines
* A target platform can be added without modifying source adapters
* Assessment can run without generation or deployment
* A target platform can initially support fit assessment and add generation or
  deployment later
* The central engines depend on versioned contracts rather than product names
* Platform-specific changes remain isolated within the corresponding module

