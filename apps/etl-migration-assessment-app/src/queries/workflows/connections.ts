import type { ColumnMetadataMap } from "@/lib/to-data-table";
import query from "./connections.dax?raw";

export const connection = "assessmentmodel";

export { query };

export const columnMetadata: ColumnMetadataMap = {
  "WorkflowConnection[WorkflowKey]": { name: "WorkflowKey", displayName: "Workflow key" },
  "WorkflowAssessment[WorkflowPath]": { name: "WorkflowPath", displayName: "Workflow" },
  "WorkflowConnection[SourceNodeId]": { name: "SourceNodeId", displayName: "Source node" },
  "WorkflowConnection[TargetNodeId]": { name: "TargetNodeId", displayName: "Target node" },
  "WorkflowConnection[SourceAnchor]": { name: "SourceAnchor", displayName: "Source anchor" },
  "WorkflowConnection[TargetAnchor]": { name: "TargetAnchor", displayName: "Target anchor" },
  "[Connection Rows]": { name: "ConnectionRows", displayName: "Rows", format: "#,##0" },
};
