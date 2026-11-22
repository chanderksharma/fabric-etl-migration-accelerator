---
title: Microsoft Fabric ETL Migration Accelerator Business Requirements
description: Business requirements for assessing legacy ETL portfolios and migrating workloads to Microsoft Fabric through a safe, extensible accelerator
author: Microsoft Industry Solutions Delivery
ms.date: 2026-11-22
ms.topic: concept
---

## Business context and background

Enterprise data modernization programs must understand and migrate estates of
legacy ETL workflows while protecting existing business semantics. The
Microsoft Fabric ETL Migration Accelerator (FEMA) addresses this need for
Alteryx Designer, Informatica PowerCenter, and Informatica Intelligent Data
Management Cloud (IDMC) estates.

The accelerator discovers and assesses source assets, estimates migration
effort and Fabric capacity, generates reviewable target artifacts, and supports
controlled deployment to a development workspace. Its design uses source
adapters and a canonical ETL representation so that source-specific formats
can be analyzed consistently.

The initiative has two related business goals:

1. Provide a usable, deterministic migration workbench for current Microsoft
   Fabric migration engagements.
2. Evolve the implementation into a pluggable solution where assessment,
   target evaluation, code generation, and deployment can be used and extended
   independently.

The product is an internal Microsoft InnerSource asset for Industry Solutions
Delivery and MCAPS modernization engagements. External distribution requires
Microsoft Legal and OSPO approval.

## Problem statement and business drivers

Migration teams face time-consuming and inconsistent estate inventory,
uncertain work estimates, and high risk when translating complex source
semantics through ad-hoc rewrites. At portfolio scale, unsupported constructs,
dependencies, runtime bindings, and capacity needs are difficult to identify
consistently before delivery begins.

The business drivers are:

* Reduce manual effort and inconsistency in estate discovery and migration
  planning.
* Identify migration risks and redesign candidates before implementation.
* Produce traceable, reviewable Fabric conversion candidates without implying
  that generated code is semantically validated.
* Improve delivery planning with transparent effort and capacity estimates.
* Reuse the assessment and generation foundation across source products and,
  over time, target platforms.
* Protect customer data and deployment credentials throughout assessment and
  delivery.

## Business objectives and success metrics

Targets and baselines remain TBD based on the stakeholder response. They must
be agreed before this BRD is approved. The measures below define what to
baseline and how to evaluate success without claiming unverified outcomes.

| ID | Objective | Measure | Baseline and target |
| --- | --- | --- | --- |
| OBJ-001 | Make estate inventory and assessment repeatable across supported source products | Analyst time to prepare a reviewed estate inventory; percentage of discovered assets with assessment results | Baseline and target to be established |
| OBJ-002 | Improve migration planning and prioritization | Percentage of assets with complexity, dependencies, risks, effort estimate, and migration wave; estimate variance against completed work | Baseline and target to be established |
| OBJ-003 | Reduce unsafe or misleading conversion outcomes | Count of unsupported constructs incorrectly emitted as deployable artifacts; percentage of generated artifacts with source traceability and validation status | Zero misleading deployable artifacts; traceability target to be agreed |
| OBJ-004 | Enable modular extension and platform choice | Time and central-engine changes required to add an approved source or target provider; number of targets evaluated against one assessment | Baseline and target to be established |
| OBJ-005 | Support secure, governed migration delivery | Customer-data or credential exposure incidents; percentage of deployments using approved identity and environment controls | Zero exposure incidents; deployment adoption target to be agreed |

Capacity and effort calculations are planning estimates, not measured
performance or migration-duration guarantees. Capacity recommendations must be
validated with representative workloads and Fabric Capacity Metrics.

## Stakeholders and roles

| Stakeholder | Role and interest |
| --- | --- |
| Business sponsor / modernization leadership | Confirms outcomes, scope, priorities, and success targets |
| Migration analysts and field architects | Intake estates, review portfolio assessment, and sequence migration waves |
| Data engineers and delivery consultants | Validate semantic mappings, complete bindings, implement redesigns, and verify parity |
| Fabric platform and capacity owners | Validate target fit, operational readiness, capacity assumptions, and workspace controls |
| DevOps and identity administrators | Configure protected CI/CD environments, allowlists, and Entra workload identity federation |
| Accelerator maintainers and contributors | Maintain contracts, source adapters, target providers, quality gates, and documentation |
| Security, privacy, and governance reviewers | Review threat controls, data handling, internal distribution, and release readiness |

The stakeholder confirmed Fabric as a stakeholder group. The accountable
business role, named sponsor, operational owner, and final approvers remain to
be confirmed.

## Scope

### In scope

* Secure discovery and assessment of Alteryx Designer, Informatica PowerCenter,
  and Informatica IDMC exports.
* A versioned canonical ETL representation that preserves source identity,
  graph structure, dependencies, and traceability.
* Target-neutral inventory, complexity, risk, and effort assessment.
* Microsoft Fabric target-fit assessment and preliminary F-SKU capacity
  estimation.
* Near-term Databricks evaluation, generation, and deployment capability, with
  provider support boundaries and release sequencing to be confirmed.
* Deterministic generation of Dataflow Gen2, Fabric Notebook, and Fabric Data
  Pipeline candidates for supported constructs.
* Explicit diagnostics and non-deployable scaffolds for unsupported semantics.
* Review, download, dry-run validation, and controlled development deployment
  through supported GitHub Actions or GitLab CI delivery paths.
* Controlled deployment to a UAT environment with QA approval.
* Portfolio reporting through local analyst tools and the Fabric-native FEMA
  workspace.
* Modular source, target-platform, and delivery-provider contracts.
* Synthetic-only test fixtures, security controls, and internal InnerSource
  collaboration.

### Out of scope

* Automatic conversion of every source operation or arbitrary embedded code.
* Executing imported workflows, scripts, or SQL as part of assessment or
  compilation.
* Claiming semantic parity or production readiness based solely on successful
  generation.
* Automatic Test or Production promotion without the documented approval and
  Fabric ALM controls.
* Synapse or Snowflake provider implementations in the current near-term scope;
  these remain roadmap placeholders unless separately approved.
* Publishing the asset externally without required Microsoft approvals.
* Customer-specific migration delivery, bespoke mappings, or real customer
  data in this repository.

## Current and future business processes

| Stage | Current process and limitation | Desired business process |
| --- | --- | --- |
| Estate intake | Teams inventory source exports with product-specific and often manual methods | Securely preview files and packages, reject unsafe inputs, deduplicate content, and confirm an immutable assessment selection |
| Portfolio assessment | Findings and estimates can vary by analyst and target assumptions can be mixed into source facts | Produce a versioned, target-neutral view of assets, operations, dependencies, complexity, risks, and estimates |
| Target selection | Current usable implementation focuses on Fabric; other targets are placeholders | Evaluate the same assessment against registered targets and compare native coverage, redesign needs, effort, capacity, and provider readiness |
| Conversion | Ad-hoc rewrites can obscure unsupported semantics and source traceability | Generate deterministic candidates only for supported operations; retain diagnostics and source-to-target traceability |
| Validation and delivery | Generated definitions require manual bindings and semantic review before promotion; current delivery documentation centers on dev | Download and review, dry-run, deploy only to approved development and UAT environments, and capture readback or verification evidence |
| Portfolio reporting | Planning information is difficult to consolidate across runs | Review portfolio, waves, blockers, capacity, and run history in analyst and leadership views |

## Business requirements

Priorities use MoSCoW: Must, Should, and Could. Requirement owners and
acceptance authority must be confirmed by the business sponsor.

| ID | Requirement | Objective | Stakeholders | Acceptance criteria | Priority |
| --- | --- | --- | --- | --- | --- |
| BR-001 | The solution must securely discover supported source assets from files, folders, and supported packages. | OBJ-001, OBJ-005 | Analysts, security reviewers | Supported Alteryx, PowerCenter, and IDMC fixtures are discovered; unsafe paths, oversized archives, and invalid inputs are rejected with actionable findings. | Must |
| BR-002 | Each source adapter must normalize supported assets into a shared, versioned ETL representation while retaining stable source identity and traceability. | OBJ-001, OBJ-004 | Maintainers, data engineers | Adapter contract tests show source assets map to canonical assets and graphs; source identifiers and locations can be traced in assessment and generated evidence. | Must |
| BR-003 | Portfolio assessment must describe the source estate independently of target selection. | OBJ-001, OBJ-002, OBJ-004 | Analysts, maintainers | Assessment can complete without selecting a target and reports consistent inventory, dependencies, complexity, risks, and estimates for a given input and rules version. | Must |
| BR-004 | The solution must evaluate target-platform fit after the neutral assessment. | OBJ-002, OBJ-004 | Analysts, platform owners | A selected target evaluation reports native coverage, required components, unsupported constructs, redesign needs, effort, operational considerations, and available generation/deployment capabilities. | Must |
| BR-005 | Users must be able to compare Microsoft Fabric and Databricks using the same assessment result. | OBJ-004 | Analysts, platform owners | Each available evaluator consumes the same versioned assessment; unsupported capabilities are clearly identified rather than presented as supported. | Must |
| BR-006 | Generation must be separate from source parsing and portfolio assessment, and consume the canonical representation. | OBJ-003, OBJ-004 | Maintainers, engineers | Target-specific generators consume canonical inputs and can be tested independently from source parsing; central orchestration does not own platform-specific syntax. | Must |
| BR-007 | Generated artifacts must identify their source, target, versions, validation state, and unresolved bindings. | OBJ-003 | Engineers, platform owners | Artifacts and diagnostics include sufficient provenance to identify source assets, generator/rules version, and readiness; unresolved bindings remain visible. | Must |
| BR-008 | Unsupported or unsafe-to-translate constructs must produce explicit diagnostics and must not appear deployable. | OBJ-003, OBJ-005 | Engineers, security reviewers | Tests verify unsupported tools or graph shapes produce scaffold/blocked diagnostics and no create-item deployment envelope. | Must |
| BR-009 | Deployment must be optional, independently selectable, and preceded by dry-run validation. | OBJ-003, OBJ-005 | Engineers, DevOps | Users can stop after assessment or generation and retain outputs; deployment cannot proceed when required validation or authorization is absent. | Must |
| BR-010 | Target deployment providers and CI/CD delivery providers must be independently composable. | OBJ-004, OBJ-005 | Maintainers, DevOps | A target deployer is not hard-coded to one CI/CD provider; configured delivery channels use explicit allowlists and return status and verification evidence. | Should |
| BR-011 | Assessment outputs, extension contracts, and persisted artifacts must be versioned and incompatible inputs must fail explicitly. | OBJ-002, OBJ-004 | Maintainers, analysts | Version changes are represented in outputs; incompatible cached or persisted results are rejected with a clear diagnostic rather than silently reinterpreted. | Must |
| BR-012 | Adding a source or target provider must not break existing supported capabilities. | OBJ-001, OBJ-004 | Maintainers, contributors | Contract and regression suites demonstrate compatibility for existing Alteryx, PowerCenter, IDMC, and Fabric behavior when a provider is added or updated. | Must |
| BR-013 | Capacity and effort outputs must expose assumptions and uncertainty and must not be represented as guaranteed outcomes. | OBJ-002 | Analysts, capacity owners, leadership | Reports identify model version, inputs, exclusions, assumptions, and estimate status; capacity sizing documentation requires representative workload validation. | Must |
| BR-014 | The solution must protect customer data, credentials, and deployment identities. | OBJ-005 | Security, privacy, DevOps | Repository fixtures contain synthetic data only; sensitive evidence is redacted; authenticated deployment uses approved protected environments and identity controls. | Must |
| BR-015 | Users must be able to review portfolio results and export assessment evidence for planning. | OBJ-001, OBJ-002 | Analysts, leadership | A completed run exposes asset-level detail and portfolio summaries; JSON/CSV exports preserve the documented fields and protect against spreadsheet formula execution. | Should |
| BR-016 | The solution must support controlled development and UAT deployment, with QA approval and governed promotion beyond UAT. | OBJ-003, OBJ-005 | QA, DevOps, platform owners | Development and UAT deployment requirements are documented and verified; QA approves UAT using agreed evidence; promotion beyond UAT uses protected approvals and adjacent Fabric Deployment Pipeline stages. | Must |

## Data and reporting requirements

The solution must report, at minimum:

* Assessment run identity, time, source family, discovered/assessed/failed
  asset counts, and rules versions.
* Per-asset source identity, operation inventory, dependencies, data endpoints,
  complexity, wave, estimated effort, target fit, and diagnostics.
* Portfolio summaries by source product, complexity, target, wave, and
  readiness state.
* Capacity scenarios, assumptions, modeled coverage, exclusions, and
  component-level CU contributions.
* Generated artifact provenance, unresolved bindings, and validation status.
* Deployment outcome and verification evidence when deployment is selected.

The leadership reporting experience currently groups portfolio insights into
Executive Summary, Wave Plan, Blockers & Risks, Fabric Capacity, and Run
History. Business owners must confirm whether these report measures and labels
meet their decision needs.

## Benefits and high-level economics

Expected benefits include reduced manual discovery effort, more consistent
migration planning, earlier visibility of redesign work, safer conversion
review, and reusable provider implementations. The reviewed repository does
not provide measured savings, customer outcomes, licensing costs, or a
validated return-on-investment model. Benefits and economics must be
quantified using pilot engagements before external or investment claims are
made.

An existing architecture-planning estimate for expanding shared contracts,
Fabric extraction, Databricks support, and validation is 18-24 person-weeks,
with an 8-week planning baseline for a three-developer team plus up to two
weeks for release validation. This is a planning estimate, not an approved
budget or committed schedule.

## Assumptions, constraints, dependencies, and risks

### Assumptions and constraints

* Core assessment and generation remain deterministic and do not execute
  imported workflows, expressions, scripts, or SQL.
* Estimates are versioned heuristics and must be calibrated against delivery
  outcomes and representative Fabric runs.
* Generated artifacts remain unvalidated until bindings are completed and
  semantic parity is independently verified.
* Only synthetic source fixtures may be committed or attached to issues.
* Current implemented source scope is Alteryx, PowerCenter, and IDMC; current
  implemented target scope is Microsoft Fabric. Databricks is a stakeholder-
  requested near-term extension, not a capability certified by the current
  release.
* Development and UAT deployment require approved workspaces and identity
  authorization. QA approval is required for UAT; promotion beyond UAT remains
  governed.
* The recommended implementation shape is a modular monolith with
  package/manifest-based provider discovery, not remote plugin execution.

### Dependencies

* Stable canonical ETL and provider contracts with explicit versioning.
* Source exports and deterministic mappings for the supported source
  constructs.
* Microsoft Fabric workspace, capacity, and API availability for validation.
* Entra identity configuration, protected CI/CD environments, repository or
  project allowlists, and Fabric permissions.
* Business and platform experts to review semantic mappings, capacity models,
  and target readiness.

### Risks and mitigations

| Risk | Business impact | Mitigation |
| --- | --- | --- |
| Unsupported source semantics are mistaken for successful conversion | Incorrect data or operational behavior after migration | Fail closed, emit explicit diagnostics, require independent parity review, and exclude scaffolds from deployment plans |
| Heuristic estimates are treated as commitments | Budget and schedule decisions are based on false precision | Show assumptions, model versions, coverage, and exclusions; compare estimates with actual delivery data |
| New providers destabilize current behavior | Regression in existing migration engagements | Version contracts, use provider contract tests, and preserve compatibility tests for existing sources and Fabric outputs |
| Customer data or secrets enter source control or outputs | Privacy, security, and compliance incident | Enforce synthetic-only fixtures, redaction, archive/path protections, secretless identity, and protected deployment environments |
| Fabric API limitations block automation | Deployment or validation delays | Use dry runs, readback and saved-query validation where supported, and report unavailable checks explicitly |
| Capacity recommendations do not match production workloads | Over- or under-provisioned Fabric capacity | Validate representative workflows and measured CU consumption before purchase or reservation |
| Databricks delivery boundaries are not yet specified | Scope and schedule expand beyond the existing Fabric-centered implementation | Confirm supported operations, validation, deployment, and delivery sequencing before commitment |
| Ownership and business outcome targets remain unclear | Adoption and investment decisions cannot be evaluated | Confirm sponsor, product owner, operational owner, baselines, targets, and approval authorities before sign-off |

## Approval and open decisions

The BRD is a baseline derived from the current repository and its documented
business requirements. The following decisions remain open:

1. What measurable targets and timeframes should be set for analyst effort,
   assessment coverage, estimate accuracy, and adoption?
2. Which accountable business role and named approvers own the confirmed Fabric
   stakeholder group?
3. What supported operations and release sequencing are expected for the
   requested near-term Databricks evaluation, generation, and deployment?
4. What QA evidence and approval authority are required for UAT, and which
   stages are required after UAT?
5. Which representative workloads from the CK project can establish baselines
   without placing customer data in this repository?

Approval record: Pending business and platform stakeholder review.
