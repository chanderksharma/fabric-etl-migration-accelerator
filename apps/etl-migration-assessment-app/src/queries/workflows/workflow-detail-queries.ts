import type { QueryDefinition } from "@/components/semantic-visuals";
import { columnMetadata as toolMetadata } from "@/queries/technical/tools";
import { columnMetadata as findingMetadata } from "@/queries/technical/findings";
import { columnMetadata as dependencyMetadata } from "@/queries/technical/dependencies";
import { columnMetadata as nodeMetadata } from "./nodes";
import { columnMetadata as connectionMetadata } from "./connections";

const idleQuery: QueryDefinition = {
  connection: "",
  query: "",
  columnMetadata: {},
};

const sha256Pattern = /^[0-9a-f]{64}$/i;

function assertWorkflowKey(workflowKey: string): string {
  if (!sha256Pattern.test(workflowKey)) {
    throw new Error("Invalid workflow key for parameterized evidence query.");
  }
  return workflowKey;
}

export function workflowNodesQuery(workflowKey?: string): QueryDefinition {
  if (!workflowKey) return idleQuery;
  const key = assertWorkflowKey(workflowKey);
  return {
    connection: "assessmentmodel",
    columnMetadata: nodeMetadata,
    query: `EVALUATE
TOPN(
    1000,
    CALCULATETABLE(
        SUMMARIZECOLUMNS(
            'WorkflowNode'[WorkflowKey],
            'WorkflowAssessment'[WorkflowPath],
            'WorkflowNode'[NodeId],
            'WorkflowNode'[NodeName],
            'WorkflowNode'[NodeLabel],
            'WorkflowNode'[Plugin],
            'WorkflowNode'[SupportCategory],
            'WorkflowNode'[Disabled],
            'WorkflowNode'[X],
            'WorkflowNode'[Y],
            "Node Rows", COUNTROWS('WorkflowNode')
        ),
        'AssessmentRun'[IsLatestCompletedRun] = TRUE(),
        'WorkflowNode'[WorkflowKey] = "${key}"
    ),
    'WorkflowNode'[NodeId], ASC
)
ORDER BY 'WorkflowNode'[NodeId] ASC`,
  };
}

export function workflowConnectionsQuery(workflowKey?: string): QueryDefinition {
  if (!workflowKey) return idleQuery;
  const key = assertWorkflowKey(workflowKey);
  return {
    connection: "assessmentmodel",
    columnMetadata: connectionMetadata,
    query: `EVALUATE
TOPN(
    1000,
    CALCULATETABLE(
        SUMMARIZECOLUMNS(
            'WorkflowConnection'[WorkflowKey],
            'WorkflowConnection'[SourceNodeId],
            'WorkflowConnection'[TargetNodeId],
            'WorkflowConnection'[SourceAnchor],
            'WorkflowConnection'[TargetAnchor],
            "Connection Rows", COUNTROWS('WorkflowConnection')
        ),
        'AssessmentRun'[IsLatestCompletedRun] = TRUE(),
        'WorkflowConnection'[WorkflowKey] = "${key}"
    ),
    'WorkflowConnection'[SourceNodeId], ASC,
    'WorkflowConnection'[TargetNodeId], ASC
)
ORDER BY 'WorkflowConnection'[SourceNodeId] ASC, 'WorkflowConnection'[TargetNodeId] ASC`,
  };
}

export function workflowFindingsQuery(workflowKey?: string): QueryDefinition {
  if (!workflowKey) return idleQuery;
  const key = assertWorkflowKey(workflowKey);
  return {
    connection: "assessmentmodel",
    columnMetadata: findingMetadata,
    query: `EVALUATE
TOPN(
    1000,
    CALCULATETABLE(
        SUMMARIZECOLUMNS(
            'Finding'[WorkflowKey],
            'WorkflowAssessment'[WorkflowPath],
            'Finding'[FindingType],
            'Finding'[FindingText],
            "Finding Count", [Static Findings]
        ),
        'AssessmentRun'[IsLatestCompletedRun] = TRUE(),
        'Finding'[WorkflowKey] = "${key}"
    ),
    'Finding'[FindingType], ASC,
    'Finding'[FindingText], ASC
)
ORDER BY 'Finding'[FindingType] ASC, 'Finding'[FindingText] ASC`,
  };
}

export function workflowDependenciesQuery(workflowKey?: string): QueryDefinition {
  if (!workflowKey) return idleQuery;
  const key = assertWorkflowKey(workflowKey);
  return {
    connection: "assessmentmodel",
    columnMetadata: dependencyMetadata,
    query: `EVALUATE
TOPN(
    1000,
    CALCULATETABLE(
        SUMMARIZECOLUMNS(
            'Dependency'[WorkflowKey],
            'WorkflowAssessment'[WorkflowPath],
            'Dependency'[DependencyReference],
            "Dependency Count", [Dependencies]
        ),
        'AssessmentRun'[IsLatestCompletedRun] = TRUE(),
        'Dependency'[WorkflowKey] = "${key}"
    ),
    'Dependency'[DependencyReference], ASC
)
ORDER BY 'Dependency'[DependencyReference] ASC`,
  };
}

export function workflowToolsQuery(workflowKey?: string): QueryDefinition {
  if (!workflowKey) return idleQuery;
  const key = assertWorkflowKey(workflowKey);
  return {
    connection: "assessmentmodel",
    columnMetadata: toolMetadata,
    query: `EVALUATE
TOPN(
    1000,
    CALCULATETABLE(
        SUMMARIZECOLUMNS(
            'ToolInventory'[WorkflowKey],
            'WorkflowAssessment'[WorkflowPath],
            'ToolInventory'[ToolName],
            'ToolInventory'[SupportCategory],
            "Tool Count", SUM('ToolInventory'[ToolCount])
        ),
        'AssessmentRun'[IsLatestCompletedRun] = TRUE(),
        'ToolInventory'[WorkflowKey] = "${key}"
    ),
    'ToolInventory'[ToolName], ASC
)
ORDER BY 'ToolInventory'[ToolName] ASC`,
  };
}
