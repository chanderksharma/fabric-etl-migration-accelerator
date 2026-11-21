import { describe, expect, it } from "vitest";

import {
  workflowConnectionsQuery,
  workflowDependenciesQuery,
  workflowFindingsQuery,
  workflowNodesQuery,
  workflowToolsQuery,
} from "@/queries/workflows/workflow-detail-queries";

describe("workflow detail queries", () => {
  const validKey = "a".repeat(64);

  it("returns idle queries when no workflow key is selected", () => {
    expect(workflowNodesQuery().connection).toBe("");
    expect(workflowConnectionsQuery().query).toBe("");
    expect(workflowFindingsQuery().query).toBe("");
    expect(workflowDependenciesQuery().query).toBe("");
    expect(workflowToolsQuery().query).toBe("");
  });

  it("scopes DAX filters to a validated SHA-256 WorkflowKey", () => {
    expect(workflowNodesQuery(validKey).query).toContain(`'WorkflowNode'[WorkflowKey] = "${validKey}"`);
    expect(workflowConnectionsQuery(validKey).query).toContain(`'WorkflowConnection'[WorkflowKey] = "${validKey}"`);
    expect(workflowFindingsQuery(validKey).query).toContain(`'Finding'[WorkflowKey] = "${validKey}"`);
    expect(workflowDependenciesQuery(validKey).query).toContain(`'Dependency'[WorkflowKey] = "${validKey}"`);
    expect(workflowToolsQuery(validKey).query).toContain(`'ToolInventory'[WorkflowKey] = "${validKey}"`);
  });

  it("rejects non-SHA-256 workflow keys to prevent DAX injection", () => {
    expect(() => workflowNodesQuery('bad" OR 1=1')).toThrow("Invalid workflow key");
  });
});
