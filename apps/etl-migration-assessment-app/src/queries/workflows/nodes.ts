import type { ColumnMetadataMap } from "@/lib/to-data-table";
import query from "./nodes.dax?raw";

export const connection = "assessmentmodel";

export { query };

export const columnMetadata: ColumnMetadataMap = {
  "WorkflowNode[WorkflowKey]": { name: "WorkflowKey", displayName: "Workflow key" },
  "WorkflowAssessment[WorkflowPath]": { name: "WorkflowPath", displayName: "Workflow" },
  "WorkflowNode[NodeId]": { name: "NodeId", displayName: "Node ID" },
  "WorkflowNode[NodeName]": { name: "NodeName", displayName: "Tool" },
  "WorkflowNode[NodeLabel]": { name: "NodeLabel", displayName: "Label" },
  "WorkflowNode[Plugin]": { name: "Plugin", displayName: "Plugin" },
  "WorkflowNode[SupportCategory]": { name: "SupportCategory", displayName: "Support category" },
  "WorkflowNode[Disabled]": { name: "Disabled", displayName: "Disabled" },
  "WorkflowNode[X]": { name: "X", displayName: "X" },
  "WorkflowNode[Y]": { name: "Y", displayName: "Y" },
  "[Node Rows]": { name: "NodeRows", displayName: "Rows", format: "#,##0" },
};
