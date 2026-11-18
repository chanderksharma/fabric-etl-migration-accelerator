Feature: Multi-source ETL to Microsoft Fabric migration acceleration
  Enable analysts to assess Alteryx Designer, Informatica PowerCenter, and
  Informatica IDMC estates and generate reviewable, deployable Fabric
  components without overstating unsupported semantics.

  Scenario: Assess a supported Alteryx estate
    Given an analyst selects Alteryx workflows or packages
    When the analyst confirms the immutable preview
    Then every workflow is assessed with versioned diagnostics

  Scenario: Route native Fabric components
    Given a parsed workflow graph
    When generation evaluates the component routing policy
    Then Dataflow Gen2 is preferred over Fabric Notebook
    And only native components receive create-item envelopes

  Scenario: Deploy through GitHub Actions
    Given an approved dev workspace and GitHub environment
    When the analyst triggers deployment
    Then the existing item is updated idempotently
    And the saved definition is validated

  Scenario: Preserve unsupported semantics
    Given a workflow without a native compiler route
    When generation completes
    Then diagnostics are retained
    And no deployable create-item envelope is emitted
