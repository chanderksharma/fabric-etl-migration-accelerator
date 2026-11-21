import type { ColumnMetadataMap } from "@/lib/to-data-table";
import query from "./tools.dax?raw";

export const connection = "assessmentmodel";

export { query };

export const columnMetadata: ColumnMetadataMap = {
  "ToolInventory[WorkflowKey]": { name: "WorkflowKey", displayName: "Workflow key" },
  "WorkflowAssessment[WorkflowPath]": { name: "WorkflowPath", displayName: "Workflow" },
  "ToolInventory[ToolName]": { name: "ToolName", displayName: "Tool" },
  "ToolInventory[SupportCategory]": { name: "SupportCategory", displayName: "Support category" },
  "[Tool Count]": { name: "ToolCount", displayName: "Count", format: "#,##0" },
};
