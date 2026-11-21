import type { ColumnMetadataMap } from "@/lib/to-data-table";
import query from "./dependencies.dax?raw";

export const connection = "assessmentmodel";

export { query };

export const columnMetadata: ColumnMetadataMap = {
  "Dependency[WorkflowKey]": { name: "WorkflowKey", displayName: "Workflow key" },
  "WorkflowAssessment[WorkflowPath]": { name: "WorkflowPath", displayName: "Workflow" },
  "Dependency[DependencyReference]": { name: "DependencyReference", displayName: "Dependency" },
  "[Dependency Count]": { name: "DependencyCount", displayName: "Count", format: "#,##0" },
};
