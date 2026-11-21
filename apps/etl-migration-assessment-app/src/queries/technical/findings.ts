import type { ColumnMetadataMap } from "@/lib/to-data-table";
import query from "./findings.dax?raw";

export const connection = "assessmentmodel";

export { query };

export const columnMetadata: ColumnMetadataMap = {
  "Finding[WorkflowKey]": { name: "WorkflowKey", displayName: "Workflow key" },
  "WorkflowAssessment[WorkflowPath]": { name: "WorkflowPath", displayName: "Workflow" },
  "Finding[FindingType]": { name: "FindingType", displayName: "Finding type" },
  "Finding[FindingText]": { name: "FindingText", displayName: "Finding" },
  "[Finding Count]": { name: "FindingCount", displayName: "Count", format: "#,##0" },
};
