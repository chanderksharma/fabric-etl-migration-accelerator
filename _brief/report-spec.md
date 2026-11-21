---
title: ETL Migration Assessment report specification
description: Locked planning specification for a Direct Lake Power BI report over migration assessment results
ms.date: 2026-11-21
ms.topic: concept
---

## Report identity

- Report name: ETL Migration Assessment
- Semantic model: ETL Migration Assessment Model
- Audience: Executives and migration leadership, with analyst and engineering drillthrough
- Primary purpose: Review portfolio readiness, prioritize migration waves, and inspect workflow evidence
- Delivery target: Build locally, validate visually, then publish to `fabric-dev` after approval
- Current phase: Approval pending

## Semantic model binding

- Entry mode: No Model
- Planned model mode: Direct Lake over `etl_assessment` Lakehouse Delta tables
- Workspace: `fabric-dev`
- Model name: ETL Migration Assessment Model
- Report binding: Resolve workspace and semantic-model IDs dynamically after model creation

## User decisions and constraints

- Retain all assessment runs.
- Default every page to the newest completed run through `AssessmentRun[IsLatestCompletedRun] = TRUE`.
- Provide a run slicer so users can inspect historical runs.
- Use a Fabric Capacity Metrics–inspired operational design: compact telemetry cards, dense evidence tables, restrained navigation, and clear exception colors.
- Do not show or model effort estimates.
- Preserve the existing notebook assessment and compiler-backed target logic.
- Phase 1 creates the governed report. Fabric App upload and notebook-run controls are deferred to Phase 2.
- Publish only after this specification is approved and local report validation succeeds.

## First-build scope

### Included

1. Persist normalized assessment and evidence Delta tables from the Fabric notebook.
2. Create a Direct Lake semantic model.
3. Create five Power BI report pages.
4. Validate PBIR, open in Power BI Desktop, and review screenshots.
5. Publish the model and report to `fabric-dev`.

### Deferred

- File upload through an application.
- Triggering notebook runs from a custom application.
- Editable workflow decisions or annotations.
- Native interactive source-graph rendering. The first release uses bounded connection and node evidence tables on the workflow drillthrough page.
- Fabric App implementation.

## Planned Lakehouse schema

### AssessmentRun

Grain: one assessment execution.

- `RunId`
- `RunLabel`
- `StartedAtUtc`
- `CompletedAtUtc`
- `Status`
- `WorkflowCount`
- `FailedCount`
- `SkippedCount`
- `RulesVersion`
- `IsLatestCompletedRun`

### WorkflowAssessment

Grain: one assessed asset in one run.

- `WorkflowKey`
- `RunId`
- `WorkflowPath`
- `SourcePlatform`
- `AssetType`
- `NativeId`
- `Folder`
- `ToolCount`
- `ConnectionCount`
- `ComplexityScore`
- `ComplexityBand`
- `RecommendedTarget`
- `MigrationWave`
- `RecommendationReason`
- `RegistryVersion`

### ToolInventory

Grain: one tool or operation type per workflow and run.

- `RunId`
- `WorkflowKey`
- `ToolName`
- `ToolCount`
- `SupportCategory`

### Finding

Grain: one bounded, redacted finding per workflow and run.

- `RunId`
- `WorkflowKey`
- `FindingType`
- `FindingText`

### Dependency

Grain: one redacted dependency reference per workflow and run.

- `RunId`
- `WorkflowKey`
- `DependencyReference`

### WorkflowNode

Grain: one bounded graph node per workflow and run.

- `RunId`
- `WorkflowKey`
- `NodeId`
- `NodeName`
- `NodeLabel`
- `Plugin`
- `SupportCategory`
- `Disabled`
- `X`
- `Y`

### WorkflowConnection

Grain: one bounded graph connection per workflow and run.

- `RunId`
- `WorkflowKey`
- `SourceNodeId`
- `TargetNodeId`
- `SourceAnchor`
- `TargetAnchor`

## Model relationships

- `AssessmentRun[RunId]` one-to-many `WorkflowAssessment[RunId]`
- `WorkflowAssessment[WorkflowKey]` one-to-many `ToolInventory[WorkflowKey]`
- `WorkflowAssessment[WorkflowKey]` one-to-many `Finding[WorkflowKey]`
- `WorkflowAssessment[WorkflowKey]` one-to-many `Dependency[WorkflowKey]`
- `WorkflowAssessment[WorkflowKey]` one-to-many `WorkflowNode[WorkflowKey]`
- `WorkflowAssessment[WorkflowKey]` one-to-many `WorkflowConnection[WorkflowKey]`
- All relationships use single-direction filtering from parent to child.

## Required measures

- `Assessed Assets`
- `High Complexity Assets`
- `Pilot Assets`
- `Redesign Assets`
- `Manual Review Assets`
- `Average Complexity Score`
- `Source Components`
- `Connections`
- `Dependencies`
- `Static Findings`

## Narrative

- Core story: Show how ready the estate is, where complexity and unsupported behavior concentrate, and what should migrate next.
- Audience promise: Leadership receives a compact decision view; analysts can filter, rank, and drill into evidence for one workflow.
- Key questions:
  - How many assets are ready for a migration wave?
  - Which targets and source platforms dominate the portfolio?
  - Which workflows create the most technical risk?
  - What evidence supports a workflow target and wave?

## Page plan

1. Portfolio Migration Summary
   - Archetype: Executive Summary
   - Purpose: Establish readiness, target distribution, wave distribution, and highest-complexity workflows.
2. Workflow Assessment Register
   - Archetype: Analytical Canvas
   - Purpose: Search, filter, rank, and drill through the assessed estate.
3. Evidence-Based Migration Plan
   - Archetype: Operational Monitor
   - Purpose: Review technical wave allocation, target mix, next actions, and backlog.
4. Technical Assessment Evidence
   - Archetype: Analytical Canvas
   - Purpose: Review mapping coverage, findings, dependencies, and connection evidence.
5. Workflow Assessment Detail
   - Archetype: Drillthrough
   - Purpose: Explain one workflow's recommendation, mapping evidence, risks, and validation requirements.

## Design system summary

- Design identity: Fabric Capacity Metrics–inspired operational telemetry.
- Canvas: 1920 by 1080.
- Navigation: Consistent page navigator; workflow table uses drillthrough to the detail page.
- Typography: Aptos Display for titles and Aptos for labels, values, and tables.
- Background: `#F3F2F1`.
- Surface: `#FFFFFF`.
- Primary telemetry blue: `#0078D4`.
- Success green: `#107C10`.
- Pilot purple: `#8764B8`.
- Warning amber: `#F59E0B`.
- Redesign red: `#D13438`.
- Text: `#242424`.
- Muted text: `#605E5C`.
- Accessibility: WCAG AA contrast, alt text on every chart, and non-color status labels.

## Canonical design contract

```yaml
Design Brief:
  generated_by: powerbi-report-cli
  contract_version: 1
  mode: greenfield
  design_identity:
    tone: "Fabric Capacity Metrics operational telemetry with neutral surfaces, dense evidence, and exception-led color"
    signature: "Compact KPI strip followed by balanced telemetry panels and a high-density evidence table"
  archetype: Executive Summary
  navigation_model: page_navigator
  color_map:
    - measure: WorkflowAssessment[Assessed Assets]
      color: "#0078D4"
      tint: "#DDEBF7"
    - measure: WorkflowAssessment[High Complexity Assets]
      color: "#F59E0B"
      tint: "#FFF4CE"
    - measure: WorkflowAssessment[Pilot Assets]
      color: "#8764B8"
      tint: "#EEE7F8"
    - measure: WorkflowAssessment[Redesign Assets]
      color: "#D13438"
      tint: "#FDE7E9"
  pages:
    - name: Portfolio Migration Summary
      role: landing
      archetype: Executive
      layout_variant: A
      variant_rationale: "Leadership needs the portfolio status, target mix, and exceptions before opening workflow evidence."
      navigation:
        - element: page_navigator
          action: PageNavigation
          target: Workflow Assessment Register
          label: Workflows
        - element: page_navigator
          action: PageNavigation
          target: Evidence-Based Migration Plan
          label: Migration Plan
        - element: page_navigator
          action: PageNavigation
          target: Technical Assessment Evidence
          label: Technical
      page_background: "#F3F2F1"
      layout_summary: "Compact run filter and KPI strip above three balanced distribution charts and a ranked workflow table."
      layout_contract:
        canvas: { width: 1920, height: 1080, margin: 32, gutter: 24, snap: 8 }
        grid:
          columns: 12
          rows: 12
          regions:
            header: [1, 1, 9, 2]
            filters: [9, 1, 13, 2]
            kpis: [1, 2, 13, 4]
            complexity: [1, 4, 5, 8]
            targets: [5, 4, 9, 8]
            waves: [9, 4, 13, 8]
            detail: [1, 8, 13, 13]
        placements:
          - { id: page_title, region: header, kind: textbox, text: "Portfolio Migration Summary" }
          - { id: run_slicer, region: filters, kind: slicer, field_bindings: "AssessmentRun[RunId]", slicer_type: dropdown, slot: 1, of: 2 }
          - { id: source_slicer, region: filters, kind: slicer, field_bindings: "WorkflowAssessment[SourcePlatform]", slicer_type: dropdown, slot: 2, of: 2 }
          - { id: assessed_card, region: kpis, kind: cardVisual, purpose: "How many assets were assessed?", field_bindings: "WorkflowAssessment[Assessed Assets]", color_strategy: measure_match, slot: 1, of: 4 }
          - { id: high_card, region: kpis, kind: cardVisual, purpose: "How many assets are high complexity?", field_bindings: "WorkflowAssessment[High Complexity Assets]", color_strategy: measure_match, slot: 2, of: 4 }
          - { id: pilot_card, region: kpis, kind: cardVisual, purpose: "How many assets require a pilot?", field_bindings: "WorkflowAssessment[Pilot Assets]", color_strategy: measure_match, slot: 3, of: 4 }
          - { id: redesign_card, region: kpis, kind: cardVisual, purpose: "How many assets require redesign?", field_bindings: "WorkflowAssessment[Redesign Assets]", color_strategy: measure_match, slot: 4, of: 4 }
          - { id: complexity_chart, region: complexity, kind: barChart, purpose: "How is technical complexity distributed?", field_bindings: { Category: "WorkflowAssessment[ComplexityBand]", Y: "WorkflowAssessment[Assessed Assets]" }, sort_policy: value_desc, color_strategy: semantic }
          - { id: target_chart, region: targets, kind: barChart, purpose: "Which Fabric targets are recommended?", field_bindings: { Category: "WorkflowAssessment[RecommendedTarget]", Y: "WorkflowAssessment[Assessed Assets]" }, sort_policy: value_desc, color_strategy: unique }
          - { id: wave_chart, region: waves, kind: columnChart, purpose: "How is the portfolio allocated across migration waves?", field_bindings: { Category: "WorkflowAssessment[MigrationWave]", Y: "WorkflowAssessment[Assessed Assets]" }, sort_policy: natural_order, color_strategy: semantic }
          - { id: ranked_workflows, region: detail, kind: tableEx, purpose: "Which workflows have the highest technical complexity?", field_bindings: ["WorkflowAssessment[WorkflowPath]", "WorkflowAssessment[ComplexityScore]", "WorkflowAssessment[ComplexityBand]", "WorkflowAssessment[RecommendedTarget]", "WorkflowAssessment[MigrationWave]"], sort_policy: value_desc }
        space_audit:
          content_cell_count: 132
          placed_cell_count: 132
          empty_cell_pct: 0
          unplaced_regions: []
          largest_region: { name: detail, pct_of_content: 45 }
          balance_rationale: "The ranked table receives the largest region because it carries the evidence behind the compact KPI and distribution summary."
    - name: Workflow Assessment Register
      role: detail
      archetype: Analytical
      layout_variant: B
      variant_rationale: "Analysts need high-density filtering and a dominant workflow register."
      navigation:
        - { element: page_navigator, action: PageNavigation, target: Portfolio Migration Summary, label: Portfolio }
        - { element: page_navigator, action: PageNavigation, target: Evidence-Based Migration Plan, label: Migration Plan }
        - { element: page_navigator, action: PageNavigation, target: Technical Assessment Evidence, label: Technical }
      page_background: "#F3F2F1"
      layout_summary: "Search and filter rail beside the workflow table, with a compact selection context strip."
      layout_contract:
        canvas: { width: 1920, height: 1080, margin: 32, gutter: 24, snap: 8 }
        grid:
          columns: 12
          rows: 12
          regions:
            header: [1, 1, 9, 2]
            filters: [9, 1, 13, 2]
            rail: [1, 2, 3, 13]
            register: [3, 2, 13, 11]
            context: [3, 11, 13, 13]
        placements:
          - { id: page_title, region: header, kind: textbox, text: "Workflow Assessment Register" }
          - { id: run_slicer, region: filters, kind: slicer, field_bindings: "AssessmentRun[RunId]", slicer_type: dropdown, slot: 1, of: 2 }
          - { id: path_search, region: filters, kind: slicer, field_bindings: "WorkflowAssessment[WorkflowPath]", slicer_type: dropdown, slot: 2, of: 2 }
          - { id: source_filter, region: rail, kind: slicer, field_bindings: "WorkflowAssessment[SourcePlatform]", slicer_type: dropdown, slot: 1, of: 4 }
          - { id: complexity_filter, region: rail, kind: slicer, field_bindings: "WorkflowAssessment[ComplexityBand]", slicer_type: list, slot: 2, of: 4 }
          - { id: target_filter, region: rail, kind: slicer, field_bindings: "WorkflowAssessment[RecommendedTarget]", slicer_type: dropdown, slot: 3, of: 4 }
          - { id: wave_filter, region: rail, kind: slicer, field_bindings: "WorkflowAssessment[MigrationWave]", slicer_type: list, slot: 4, of: 4 }
          - { id: workflow_table, region: register, kind: tableEx, purpose: "Which workflows match the analyst's current technical filters?", field_bindings: ["WorkflowAssessment[WorkflowPath]", "WorkflowAssessment[SourcePlatform]", "WorkflowAssessment[AssetType]", "WorkflowAssessment[ToolCount]", "WorkflowAssessment[ConnectionCount]", "WorkflowAssessment[ComplexityScore]", "WorkflowAssessment[ComplexityBand]", "WorkflowAssessment[RecommendedTarget]", "WorkflowAssessment[MigrationWave]"], sort_policy: value_desc }
          - { id: selected_context, region: context, kind: textbox, text: "Select a workflow row and drill through for source graph, design, risk, validation, and mappings." }
        space_audit:
          content_cell_count: 110
          placed_cell_count: 110
          empty_cell_pct: 0
          unplaced_regions: []
          largest_region: { name: register, pct_of_content: 82 }
          balance_rationale: "The register dominates because search and comparison are the page's primary analytical jobs; filters remain in a dedicated rail."
    - name: Evidence-Based Migration Plan
      role: detail
      archetype: Operational
      layout_variant: A
      variant_rationale: "Wave allocation and exception-oriented backlog require balanced status and action views."
      navigation:
        - { element: page_navigator, action: PageNavigation, target: Portfolio Migration Summary, label: Portfolio }
        - { element: page_navigator, action: PageNavigation, target: Workflow Assessment Register, label: Workflows }
        - { element: page_navigator, action: PageNavigation, target: Technical Assessment Evidence, label: Technical }
      page_background: "#F3F2F1"
      layout_summary: "Wave KPIs, target-by-wave and wave distribution visuals above the action backlog."
      layout_contract:
        canvas: { width: 1920, height: 1080, margin: 32, gutter: 24, snap: 8 }
        grid:
          columns: 12
          rows: 12
          regions:
            header: [1, 1, 9, 2]
            filters: [9, 1, 13, 2]
            kpis: [1, 2, 13, 4]
            target_wave: [1, 4, 7, 8]
            wave_mix: [7, 4, 13, 8]
            backlog: [1, 8, 13, 13]
        placements:
          - { id: page_title, region: header, kind: textbox, text: "Evidence-Based Migration Plan" }
          - { id: run_slicer, region: filters, kind: slicer, field_bindings: "AssessmentRun[RunId]", slicer_type: dropdown, slot: 1, of: 2 }
          - { id: source_slicer, region: filters, kind: slicer, field_bindings: "WorkflowAssessment[SourcePlatform]", slicer_type: dropdown, slot: 2, of: 2 }
          - { id: wave1_card, region: kpis, kind: cardVisual, purpose: "How many assets are in Wave 1?", field_bindings: "WorkflowAssessment[Assessed Assets]", color_strategy: semantic, slot: 1, of: 4 }
          - { id: wave2_card, region: kpis, kind: cardVisual, purpose: "How many assets are in Wave 2?", field_bindings: "WorkflowAssessment[Assessed Assets]", color_strategy: semantic, slot: 2, of: 4 }
          - { id: pilot_card, region: kpis, kind: cardVisual, purpose: "How many assets require a pilot?", field_bindings: "WorkflowAssessment[Pilot Assets]", color_strategy: measure_match, slot: 3, of: 4 }
          - { id: redesign_card, region: kpis, kind: cardVisual, purpose: "How many assets require redesign?", field_bindings: "WorkflowAssessment[Redesign Assets]", color_strategy: measure_match, slot: 4, of: 4 }
          - { id: target_by_wave, region: target_wave, kind: columnChart, purpose: "Which targets appear in each migration wave?", field_bindings: { Category: "WorkflowAssessment[MigrationWave]", Legend: "WorkflowAssessment[RecommendedTarget]", Y: "WorkflowAssessment[Assessed Assets]" }, sort_policy: natural_order, color_strategy: unique }
          - { id: wave_distribution, region: wave_mix, kind: barChart, purpose: "How large is each technical migration wave?", field_bindings: { Category: "WorkflowAssessment[MigrationWave]", Y: "WorkflowAssessment[Assessed Assets]" }, sort_policy: natural_order, color_strategy: semantic }
          - { id: migration_backlog, region: backlog, kind: tableEx, purpose: "Which workflow should be reviewed next and why?", field_bindings: ["WorkflowAssessment[WorkflowPath]", "WorkflowAssessment[MigrationWave]", "WorkflowAssessment[RecommendedTarget]", "WorkflowAssessment[ComplexityScore]", "WorkflowAssessment[RecommendationReason]"], sort_policy: value_desc }
        space_audit:
          content_cell_count: 132
          placed_cell_count: 132
          empty_cell_pct: 0
          unplaced_regions: []
          largest_region: { name: backlog, pct_of_content: 45 }
          balance_rationale: "Status visuals explain the wave mix while the action backlog receives the largest evidence region."
    - name: Technical Assessment Evidence
      role: detail
      archetype: Analytical
      layout_variant: A
      variant_rationale: "Engineering reviewers need coverage metrics, mapping exceptions, findings, and raw connection evidence."
      navigation:
        - { element: page_navigator, action: PageNavigation, target: Portfolio Migration Summary, label: Portfolio }
        - { element: page_navigator, action: PageNavigation, target: Workflow Assessment Register, label: Workflows }
        - { element: page_navigator, action: PageNavigation, target: Evidence-Based Migration Plan, label: Migration Plan }
      page_background: "#F3F2F1"
      layout_summary: "Evidence KPIs and mapping coverage above findings and bounded technical registers."
      layout_contract:
        canvas: { width: 1920, height: 1080, margin: 32, gutter: 24, snap: 8 }
        grid:
          columns: 12
          rows: 12
          regions:
            header: [1, 1, 9, 2]
            filters: [9, 1, 13, 2]
            kpis: [1, 2, 13, 4]
            mappings: [1, 4, 7, 8]
            findings: [7, 4, 13, 8]
            detail: [1, 8, 13, 13]
        placements:
          - { id: page_title, region: header, kind: textbox, text: "Technical Assessment Evidence" }
          - { id: run_slicer, region: filters, kind: slicer, field_bindings: "AssessmentRun[RunId]", slicer_type: dropdown, slot: 1, of: 2 }
          - { id: workflow_slicer, region: filters, kind: slicer, field_bindings: "WorkflowAssessment[WorkflowPath]", slicer_type: dropdown, slot: 2, of: 2 }
          - { id: components_card, region: kpis, kind: cardVisual, purpose: "How many source components were parsed?", field_bindings: "WorkflowAssessment[Source Components]", color_strategy: none, slot: 1, of: 4 }
          - { id: connections_card, region: kpis, kind: cardVisual, purpose: "How many source connections were parsed?", field_bindings: "WorkflowAssessment[Connections]", color_strategy: none, slot: 2, of: 4 }
          - { id: dependencies_card, region: kpis, kind: cardVisual, purpose: "How many dependency references require review?", field_bindings: "WorkflowAssessment[Dependencies]", color_strategy: none, slot: 3, of: 4 }
          - { id: findings_card, region: kpis, kind: cardVisual, purpose: "How many static findings were recorded?", field_bindings: "WorkflowAssessment[Static Findings]", color_strategy: semantic, slot: 4, of: 4 }
          - { id: mapping_distribution, region: mappings, kind: barChart, purpose: "How are source tools mapped to implementation categories?", field_bindings: { Category: "ToolInventory[SupportCategory]", Y: "ToolInventory[ToolCount]" }, sort_policy: value_desc, color_strategy: semantic }
          - { id: findings_table, region: findings, kind: tableEx, purpose: "Which workflows contain static findings?", field_bindings: ["WorkflowAssessment[WorkflowPath]", "Finding[FindingType]", "Finding[FindingText]"], sort_policy: category_asc }
          - { id: connection_table, region: detail, kind: tableEx, purpose: "Which bounded source connections support workflow interpretation?", field_bindings: ["WorkflowAssessment[WorkflowPath]", "WorkflowConnection[SourceNodeId]", "WorkflowConnection[TargetNodeId]", "WorkflowConnection[SourceAnchor]", "WorkflowConnection[TargetAnchor]"], sort_policy: category_asc }
        space_audit:
          content_cell_count: 132
          placed_cell_count: 132
          empty_cell_pct: 0
          unplaced_regions: []
          largest_region: { name: detail, pct_of_content: 45 }
          balance_rationale: "Mapping and finding panels provide context; the connection register receives the largest region for engineering review."
    - name: Workflow Assessment Detail
      role: drillthrough
      archetype: Analytical
      layout_variant: C
      variant_rationale: "One workflow requires compact summary, mapping evidence, connections, risks, and validation actions."
      navigation:
        - { element: button, action: Back, label: Back to workflow register }
        - { element: page_navigator, action: PageNavigation, target: Portfolio Migration Summary, label: Portfolio }
      page_background: "#F3F2F1"
      layout_summary: "Workflow summary above connection and mapping tables, followed by risk and validation panels."
      layout_contract:
        canvas: { width: 1920, height: 1080, margin: 32, gutter: 24, snap: 8 }
        grid:
          columns: 12
          rows: 12
          regions:
            header: [1, 1, 10, 2]
            actions: [10, 1, 13, 2]
            summary: [1, 2, 13, 4]
            connections: [1, 4, 7, 9]
            mappings: [7, 4, 13, 9]
            risks: [1, 9, 7, 13]
            validation: [7, 9, 13, 13]
        placements:
          - { id: page_title, region: header, kind: textbox, text: "Workflow Assessment Detail" }
          - { id: back_button, region: actions, kind: button, action: Back, label: Back to workflow register }
          - { id: workflow_name, region: summary, kind: cardVisual, purpose: "Which workflow is selected?", field_bindings: "WorkflowAssessment[WorkflowPath]", color_strategy: none, slot: 1, of: 4 }
          - { id: complexity_score, region: summary, kind: cardVisual, purpose: "How complex is the selected workflow?", field_bindings: "WorkflowAssessment[ComplexityScore]", color_strategy: semantic, slot: 2, of: 4 }
          - { id: target_card, region: summary, kind: cardVisual, purpose: "Which Fabric target is recommended?", field_bindings: "WorkflowAssessment[RecommendedTarget]", color_strategy: unique, slot: 3, of: 4 }
          - { id: wave_card, region: summary, kind: cardVisual, purpose: "Which migration wave contains the workflow?", field_bindings: "WorkflowAssessment[MigrationWave]", color_strategy: semantic, slot: 4, of: 4 }
          - { id: workflow_connections, region: connections, kind: tableEx, purpose: "How do bounded source nodes connect?", field_bindings: ["WorkflowConnection[SourceNodeId]", "WorkflowConnection[TargetNodeId]", "WorkflowConnection[SourceAnchor]", "WorkflowConnection[TargetAnchor]"], sort_policy: category_asc }
          - { id: tool_mappings, region: mappings, kind: tableEx, purpose: "How are source tools mapped to Fabric implementation categories?", field_bindings: ["ToolInventory[ToolName]", "ToolInventory[ToolCount]", "ToolInventory[SupportCategory]"], sort_policy: value_desc }
          - { id: risk_findings, region: risks, kind: tableEx, purpose: "What static risks require review?", field_bindings: ["Finding[FindingType]", "Finding[FindingText]"], sort_policy: category_asc }
          - { id: validation_notes, region: validation, kind: textbox, text: "Confirm bindings and permissions; compare schemas, row counts, null handling, and business rules; test representative data and exception paths; validate monitoring and rollback before promotion." }
        space_audit:
          content_cell_count: 132
          placed_cell_count: 132
          empty_cell_pct: 0
          unplaced_regions: []
          largest_region: { name: connections, pct_of_content: 27 }
          balance_rationale: "Connection and mapping evidence receive equal analytical space; risk and validation panels complete the workflow decision."
  interaction_pattern:
    drill_targets:
      - Workflow Assessment Detail
    cross_filter_rules: "Portfolio and plan charts filter supporting tables; workflow register rows drill through to the detail page."
  accessibility:
    alt_text_strategy: "Every visual names its analytical question and summarizes the selected run and filter context."
    contrast_notes: "All text and status colors meet WCAG AA on neutral surfaces; wave and target labels accompany color."
  theme:
    base: "references/design/assets/base.json adapted to Fabric Capacity Metrics operational telemetry"
    user_overrides: "Preserve compact density, Aptos typography, neutral surfaces, and exception-led color semantics."
```

## Implementation notes

- Notebook persistence:
  - Add an explicit write gate.
  - Write one immutable `RunId` per completed assessment.
  - Update `IsLatestCompletedRun` transactionally after all result tables succeed.
  - Never store absolute workstation paths, credentials, or raw workflow expressions.
- Semantic model:
  - Create after spec approval through semantic-model authoring.
  - Validate all measures with DAX.
  - Use Direct Lake where supported.
- Report:
  - Build local PBIP/PBIR first.
  - Validate JSON and bindings.
  - Open in Power BI Desktop and capture screenshots for all five pages.
  - Publish only after the screenshot review passes.
- Security:
  - Keep all findings and dependencies redacted.
  - Apply workspace and report permissions.
  - Add row-level security only if assessment runs need audience isolation.

## Approval

Implementation is blocked until this specification is explicitly approved.
